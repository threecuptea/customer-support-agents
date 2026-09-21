from __future__ import annotations
from models.model import CustomerSupportState, FAQMatchEvals, FAQMatchResult, Order, OrderStructuredOutput,\
    ESCALATE_REASON

from langgraph.graph import END, START, StateGraph
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage, AIMessage, ChatMessage
from typing import Any
from dotenv import load_dotenv
import logging
import os
from workflow.llm import get_llm
from langchain_core.runnables import RunnableConfig

from memory import save_user_memory
from workflow.customer_support_tools import find_closest_faq, retrieve_target_order, faq_dict


load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

FAQ_MATCH_THRESHOLD = 75.0
ESCALATE_MESSAGE = "I will escalate your inquiry/ request to a human agent and somebody will contact you within 3 business days"
SYSTEM_ERROR_MESSAGE = "System error!! We cannot find your order, please try it later"
ESCALATE_REASON_FAQ = "Unable to find a satifactory answer to the customer's question"


SUMMARIZE_MESSAGE_THRESHOLD = 6
SOURCE_FAQ_FUZZY_MATCH = "faq_fuzzy_match"
SOURCE_FAQ_LLM_MATCH = "faq_llm_match"
SOURCE_FAQ_LLM_EVALS = "faq_llm_evals"
SOURCE_ORDER_RETRIEVAL = "retrieve_target_order"
SOURCE_ORDER_INQUIRY = "order_inquiry"
ROLE_FUNCTION_CALL = "function"
ROLE_AGENT = "assistant"


class CustomerSupportAgent:
    def __init__(self, checkpointer, store):
        self.checkpointer = checkpointer
        self.store = store
        # I can override model and provider to use overrides if needed
        self.summarize_llm = get_llm()
       
        # FAQ matching
        # Selected models should be customized by their speciality and strength in the production
        self.general_llm_for_faq_match_evals = get_llm().with_structured_output(FAQMatchEvals)
        self.general_llm_for_faq_match_result = get_llm().with_structured_output(FAQMatchResult)
        self.faq_context = "\n".join([f"- 'question': {key}, 'answer': {val} " for key, val in faq_dict.items()])
        self.order_llm_for_inquiry_chat = get_llm().with_structured_output(OrderStructuredOutput)


    ###############################################
    #               Summarize Node
    ###############################################
    # It's a good practice to summarize message, store in the long-term meory then delete old messages 
    # leave only a few very recent ones (the latest two messages in this case). The summarized response 
    # will be in 'summary'.
    # I did not realize that GraphState and StateSnapshot share the same meomry space
    # RemoveMessage will affect GraphState and StateSnapshot outputs.  Externally, we don't need to access GraphState
    # We can just access StateSnapshot. 'messages' of GraphState will be StateSnapshot.values["messages"]
    # and 'general_inquiry' of GraphState will be StateSnapshot.values["general_inquiry"] 
    # Borrow from https://pub.towardsai.net/your-first-real-langgraph-project-ac5eb00f923a.  Thanks              
    async def summarize_node(self, state: CustomerSupportState, config: RunnableConfig) -> dict[str, Any]:
        """Compresses the full message history into a short summary, then deletes old
        raw messages. Callers route here via `_should_summarize` (message count past
        SUMMARIZE_MESSAGE_THRESHOLD, or their own flow-specific topic-concluded signal) —
        this node itself is flow-agnostic and always summarizes when invoked.
        The summary grows richer turn by turn. Token costs stay nearly flat no matter how long
        the conversation runs.
        """
        existing_summary = state.get("summary", "")
        if existing_summary:
            # Extend the existing summary with new messages
            summarize_instruction = (
                f"Current summary:\n{existing_summary}\n\n"
                "Extend this summary with the new messages above. "
                "Keep it under 5 sentences. Focus on: the customer's name, "
                "their issue, any order(s) mentioned, and what actions were taken."
            )
        else:
            # First time summarising
            summarize_instruction = (
                "Summarise this customer support conversation in under 5 sentences. "
                "Include: the customer's name (if mentioned), their issue, "
                "any order(s) discussed, and what actions were taken so far."
            )

        messages = state["messages"] + [HumanMessage(content=summarize_instruction)]
        response = await self.summarize_llm.ainvoke(messages)  # Plain llm, no tools needed here
        # Delete all but the 2 most recent messages.
        # The summary now holds everything that was in the deleted messages.
        # It's a bad choice to keep the last two
        messages_to_delete = [
            RemoveMessage(id=m.id) for m in state["messages"][:-2]
        ]
        # Store summary in the long-term memory
        thread_id = config.get("configurable", {}).get("thread_id")
        await save_user_memory(self.store, state['customer_context'].customer_id, thread_id, response.content)

        return {
            "summary": response.content,
            "messages": messages_to_delete,
        }

    ###############################################
    #               General Nodes
    ###############################################
    # I might need to 
    async def general_faq_eval_node(self, state: CustomerSupportState) -> dict[str, Any]:
        # Draw previous conversation from the summary in this thread if any otherwise draw from the long term memory
        SYSTEM_PROMPT = f"""
        You are an intelligent customer-support agent to help decide if it is helpful to match the customer question 
        against FAQs
        Here is the customer's question: {state["general_inquiry"]}.
        Here are FAQ context: {self.faq_context}.
        Here is the summary of the previous conversation if any: {state.get("summary") if state.get("summary") else (state["messages"][-2].content if len(state["messages"]) >= 2 else "None yet")}.
        There are two matching options:
        - Matches with fuzz.partial_ratio scorer of python Rapidfuzz library. The fuzz.partial_ratio scorer finds the
        best-aligned contiguous substring of the shorter string within the longer one and scores their similarity,
        so it favors cases where the customer's question shares a close substring with an FAQ question, even if the
        two differ in length (e.g. extra words before/after).
        - LLM semantic matching
        The above options are not mutual exclusive.
        Set `rapid_fuzz_partial_ratio_match_helpful` if you think that the fuzz match option will be helpful.
        Set `llm_semantic_match_helpful` if you think the LLM semantic match will be help.
        state `reason` as needed.
        Set both flags to False if you are not sure if either one will help
        """
        # Do I use Mesage the right way.  
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        # resp should an AIMessage wrapper
        # FAQMatchEvals
        eval = await self.general_llm_for_faq_match_evals.ainvoke([system_msg])
        updates = {"faq_match_evals": eval, "general_issue_resolved": False}
        if not eval or (eval and not eval.rapid_fuzz_partial_ratio_match_helpful and not eval.llm_semantic_match_helpful):
            response = ESCALATE_MESSAGE
            message = ChatMessage(content=response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_FAQ_LLM_EVALS})
            updates["messages"] = [message]
            updates["response"] = response
            updates["escalation_reason"] = f"{ESCALATE_REASON_FAQ}: {state["general_inquiry"]}"
            updates["general_issue_resolved"] = True

        return updates

    
    # I don't like to use ToolNode, Yes, it would know the latest AI message, 
    # runs the matching functions (often at the same time), and turns the results into tool messages
    # However, ToolMessage content is always string.  I don't like to convert BaseModel to str then 
    # convert str to BaseModel back and forth.  I want it to return a BaseModel as it is
    async def general_faq_fuzz_match_node(self, state: CustomerSupportState) -> dict[str, Any]:
        result: FAQMatchResult = find_closest_faq(state["general_inquiry"])
        if result and result.confidence_score >= FAQ_MATCH_THRESHOLD:
            response = result.answer
            # Originally I want to use ToolMessage but that requires tool-call_id which will link back to AIMessage.
            # But I can use function call and not need to use LLM bind_tools
            message = ChatMessage(content=response, role= ROLE_FUNCTION_CALL, additional_kwargs={
                "source":SOURCE_FAQ_FUZZY_MATCH, "faq_match_result": result
            })
            return {
                "messages": [message],
                "response": response,
                "general_issue_resolved": True,
            }
        elif not state["faq_match_evals"].llm_semantic_match_helpful:
            response = ESCALATE_MESSAGE
            message = ChatMessage(content=response, role= ROLE_AGENT, additional_kwargs={
                "source":SOURCE_FAQ_FUZZY_MATCH})
            return {
                    "messages": [message],
                    "response": response,
                    "escalation_reason": f"{ESCALATE_REASON_FAQ}: {state["general_inquiry"]}",
                    "general_issue_resolved": True,
            }
        else:
            return {
                "general_issue_resolved": False,
            }

    async def general_faq_llm_match_node(self, state: CustomerSupportState) -> dict[str, Any]:
        SYSTEM_PROMPT = f"""
        You are an intelligent customer-support agent to help match the customer question against FAQs
        Here is the customer's question {state["general_inquiry"]}.
        Here are FAQ context: {self.faq_context}.
        Set `question` to the 'question' that is most similar to the customer's question among FAQ context.  
        Set `answer` to the corresponding 'answer' of the above `question`.
        Set `confidence_score` based upon your judgement.
        """
        # Do I use Mesage the right way.  
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        # resp should an AIMessage wrapper
        # FAQMatchEvals
        result: FAQMatchResult = await self.general_llm_for_faq_match_result.ainvoke([system_msg])
        if result and result.confidence_score >= FAQ_MATCH_THRESHOLD:
            response = result.answer
            message = AIMessage(content=response, additional_kwargs={
                "source":SOURCE_FAQ_LLM_MATCH
            })
            return {
                "messages": [message],
                "response": response,
                "general_issue_resolved": True,
            }
        else:
            response = ESCALATE_MESSAGE
            message = ChatMessage(content=response, role=ROLE_AGENT, additional_kwargs={
                "source":SOURCE_FAQ_LLM_MATCH, "faq_match_result": result,
            })
            return {
                    "messages": [message],
                    "response": response,
                    "escalation_reason": f"{ESCALATE_REASON_FAQ}: {state["general_inquiry"]}",
                    "general_issue_resolved": True,
            }


    ###############################################
    #               Order Nodes
    ###############################################
    
    async def order_continue_chat_node(self, state: CustomerSupportState) -> dict[str, Any]:
            # Need to include not only HumanMessage but also SystemMessage etc.  
        recent_conversations = "\n".join([f"- {message.content}" for message in state['messages']])
        SYSTEM_PROMPT = f"""
            You are an intelligent customer-support agent that helps answer the customer's question regarding to his/ her order.  
            Here is the target order {state['target_order'].model_dump_json()}
            Here is the most recent conversations in sequential order: {recent_conversations}.
            Here is the summary of the previous conversation: {state.get("summary") if state.get("summary") else "None yet"}.
            The above is the context of this order.
            DO NOT REPEAT the same response!!  
            You can wrap up by saying something like 'Anything else I can help you with?' if you find it is at the end of the conversation.
            set `order_issue_resolved` when it is appropriate.             
                        
            Scenarios that we are trying to cover:

            Find out what the customer is complaining about.
            if the order status is 'delivered' but the customer did not receive the shipment, ask the customer to click the tracking number link to see if there is a delivery photo taken.  
            If yes, is the photo taken in the customer's porch?  If yes, ask the customer to check with his/ her Ring's camera footage if the customer has Ring security system or 
            check with his/ her family members before the customer confirm that the shipment is stolen . UPS would not be responsible for a stolen shipment.  
            If the photo is not taken in the customer's porch or no photo taken, ask the customer to look around the house and/ or check with neighbors.
            Let the customer know that he/ she can always re-visit us after he/ she exhaust searches assuming the shipment is not stolen. 
            You will set the `escalate` flag to True if the customer re-visit us as instructed and set '{ESCALATE_REASON.HELP_LOST_SHIPMENT}' as the `escalate_reason`.

            if the order status is 'delivered' and the customer is complaining about item(s) delivered is/ are torn or damaged or bad-quality,
            tell the customer that the quality problem might be an one-off issue and direct the customer to `e-shopping.com` web site to exchange items if possible.
            if the customer like to return the product(s), please confirm with him/ her for sure before set the `intent_for_return_refund` to True and tell the customer that we will be happy to process 
            the return refund if he/ she can help us itemize product(s) to be returned.

            if the order status is 'transit', ask the customer to track the whereabouts of the shipping using the UPS's tracking number.
            if the order status is 'pending', ask the customer to wait for a couple of day.  The customer can always cancel the order if he/ she really want.
            if the customer intend to cancel the order, you will set the `escalate` flag to true and set '{ESCALATE_REASON.HELP_CANCEL_ORDER}' as the `escalate_reason`

            if the customer's conversation lead to an uncovered scenario or that you do not have an answer, please set `escalate` flag to True and set
            '{ESCALATE_REASON.HELP_ANSWER_ORDER_INQUIRY}' as the `escalate_reason`

            set `response` to what you want to reply 
            """
        
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        order_output: OrderStructuredOutput = await self.order_llm_for_inquiry_chat.ainvoke([system_msg])
        # mock llm will return order_output None
        if order_output.escalate:
            message = ChatMessage(content= ESCALATE_MESSAGE, role= ROLE_AGENT, additional_kwargs={
                    "source": SOURCE_ORDER_INQUIRY})
            return {
                "messages": [message], 
                "response": ESCALATE_MESSAGE,
                "escalation_reason": f"{order_output.escalation_reason} of order #{state['order_number_provided']}", 
                "order_issue_escalated": True,
            }
                        
        message = AIMessage(content= order_output.response, additional_kwargs={
                "source":SOURCE_ORDER_INQUIRY})            
        return {
            "messages": [message],
            "response": order_output.response,
            "order_issue_resolved": order_output.order_issue_resolved, # signal writing the summary
            "intent_for_return_refund": order_output.intent_for_return_refund,

        }

    async def order_init_chat_node(self, state: CustomerSupportState) -> dict[str, Any]:        
        target_order: Order = retrieve_target_order(state["customer_context"], state["order_number_provided"])
        if target_order:
            response = ""
            # ["delivered", "transit", "pending"]
            match target_order.status:
                case "pending": 
                    response = f"Your order is still in 'pending' status. You order on {target_order.order_date}"
                    if target_order.notes:
                        response += f"Notes say: {target_order.notes}. "
                    else:
                        response += "Notes does not provide additional information. "    
                    response += "We will ship as soon as the order is ready and sorry for the delay.  Thanks for your patience"        
                case "transit":
                    response = f"Your order is still in 'transit' status. it was estimated to arrive at {target_order.estimated_delivery_date.isoformat()}. "
                    response += "Please follow the tracking number link in the shipping email or just go to UPS web site and enter your tracking number to get the delivery update, Thanks."
                case "delivered":
                    response = f"Your order is in 'delivered' status. According to our record,  your order has been delivered on {target_order.delivery_date.isoformat()}.  Is everything O.K.?"
                case _:
                    pass

            message = ChatMessage(content=response, role= ROLE_AGENT)
            return {
                "target_order": target_order,
                "messages": [message],
                "response": response,
            }
        else:
            # It should not happen
            response = SYSTEM_ERROR_MESSAGE
            message = ChatMessage(content=response, role= ROLE_AGENT, additional_kwargs= {"source": SOURCE_ORDER_RETRIEVAL})
            return {
                "target_order": None, 
                "messages": [message],
                "response": response,
            }
            

    ###############################################
    #            Routes after a node
    ###############################################
    def route_branch(self, state: CustomerSupportState) -> str:
        # Add summarize_on_exit hook so it can be called when the customer press 'Exit'
        if state.get("summarize_on_exit"):
            return "summarize_node"
        
        match state['support_category']:
            case "general/ others":
                return "general_faq"
            case _:
                return self.route_order(state)       

    # It's not an actual route. It return node by condition.  Get around with conditional edge within conditional edge
    def route_order(self, state: CustomerSupportState) -> str:
        # Fix an error if order_number not passed or passed as 0.  Let retrieve_target_order instead of order_continue_chat_node handle 
        if not state["target_order"]:
            return "order_init"
        
        return "order_init_done"

    def _should_summarize(self, state: CustomerSupportState, topic_concluded: bool = False) -> bool:
        """Shared trigger for routing into `summarize_node`: each flow passes its own
        flow-specific 'concluded' signal (e.g. `general_issue_resolved` for the general
        inquiry flow); the message-count threshold is the only domain-agnostic part,
        shared across flows.
        It's possible that the customer will just close browser. That's why I try to summarize whenever
        the customer wrap up a topic.
        """
        return topic_concluded or len(state["messages"]) > SUMMARIZE_MESSAGE_THRESHOLD

    def route_after_general_faq_eval(self, state: CustomerSupportState) -> str:
        if self._should_summarize(state, state["general_issue_resolved"]):
            return "summarize_node"
        if state["faq_match_evals"]:
            if state["faq_match_evals"].rapid_fuzz_partial_ratio_match_helpful:
                return "general_faq_fuzz_match_node"
            if state["faq_match_evals"].llm_semantic_match_helpful:
                return "general_faq_llm_match_node"
        return "summarize_node"

    def route_after_general_faq_fuzz_match(self, state: CustomerSupportState) -> str:
        if self._should_summarize(state, state["general_issue_resolved"]):
            return "summarize_node"
        return "general_faq_llm_match_node"

    def route_after_order_continue_chat(self, state: CustomerSupportState) -> str:
            if self._should_summarize(state, 
                                      state.get("intent_for_return_refund") or  
                                      state.get("order_issue_escalated") or 
                                      state.get("order_issue_resolved")):
                return "summarize_node"
            return END 
     

    ###############################################
    #            Build the support graph
    ###############################################
    def build_support_graph(self):
        """Build and compile the main chat/ refund workflow."""
        builder = StateGraph(CustomerSupportState)
        # Harnese with RetryPolicy later
        builder.add_conditional_edges(START, self.route_branch, 
                                      {"summarize_node": "summarize_node",
                                       "general_faq": "general_faq_eval_node", 
                                       "order_init": "order_init_chat_node",
                                       "order_init_done": "order_continue_chat_node"})
        
        builder.add_node("summarize_node", self.summarize_node)
        builder.add_edge("summarize_node", END)

        builder.add_node("general_faq_eval_node", self.general_faq_eval_node)
        builder.add_conditional_edges("general_faq_eval_node", self.route_after_general_faq_eval,
            {"summarize_node": "summarize_node", "general_faq_fuzz_match_node": "general_faq_fuzz_match_node", "general_faq_llm_match_node": "general_faq_llm_match_node"})

        builder.add_node("general_faq_fuzz_match_node", self.general_faq_fuzz_match_node)
        builder.add_conditional_edges("general_faq_fuzz_match_node", self.route_after_general_faq_fuzz_match,
            {"summarize_node": "summarize_node", "general_faq_llm_match_node": "general_faq_llm_match_node"})
        
        builder.add_node("general_faq_llm_match_node", self.general_faq_llm_match_node)
        builder.add_edge("general_faq_llm_match_node", "summarize_node")

        builder.add_node("order_continue_chat_node", self.order_continue_chat_node)
        builder.add_node("order_init_chat_node", self.order_init_chat_node)

        # It's not cost effcient to inject order_continue_chat_node with long-term memory every time it was invoke.
        # Instead, I summarize here and include the content long-term memory so that 'order_continue_chat_node' has a good context   
        builder.add_edge("order_init_chat_node", "summarize_node") 

        builder.add_conditional_edges("order_continue_chat_node", self.route_after_order_continue_chat,
            {"summarize_node": "summarize_node", END: END})
        
        graph = builder.compile(checkpointer = self.checkpointer, store = self.store)
        self.graph = graph
        return graph
    

    