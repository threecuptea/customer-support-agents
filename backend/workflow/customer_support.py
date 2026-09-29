from __future__ import annotations
from models.model import CustomerSupportState, FAQMatchEvals, FAQMatchResult, Order, OrderStructuredOutput,\
    ESCALATE_REASON, OrderRevisitEval, ExchangeReturnRefundAction, ExchangeReturnReason, ExchangeOrReturnInput

from langgraph.graph import END, START, StateGraph
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage, AIMessage, ChatMessage
from typing import Any
from dotenv import load_dotenv
import logging
import os
from workflow.llm import get_llm
from langchain_core.runnables import RunnableConfig
from datetime import timedelta

from memory import save_user_memory
from workflow.customer_support_utils import find_closest_faq, retrieve_target_order, faq_dict, RETURN_POLICY


load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

FAQ_MATCH_THRESHOLD = 75.0
ESCALATE_MESSAGE = "I will escalate your inquiry/ request to a human agent and somebody will contact you within 3 business days"
SYSTEM_ERROR_MESSAGE = "System error!! We cannot find your order, please try it later"
ESCALATE_REASON_FAQ = "Unable to find a satifactory answer to the customer's question"

PREFIX_ANSWER_QUESTION = "I don't have an answer to your question."
PREFIX_LOST_SHIPMENT = "You need help to handle your lost shipment."
PREFIX_CANCEL_ORDER = "You need help to cancel your order."
PREFIX_CHECK_RETURN_REFIND_STATUS = "You need help to check the return refund status of your order."
PREFIX_NEED_EXPEDIT_REPLACEMENT = "need to expedite a replacement"
PREFIX_RCVD_DAMAGED_PRODUCT = "You received broken or defective items or a product with missing parts"
PREFIX_RCVD_WRONG_ITEM = "You received an wrong item"
PREFIX_FOUND_BETTER_PRICE = "You found that our competitor offer a better price and we like to see if we can price match that."


SUMMARIZE_MESSAGE_THRESHOLD = 6
FUNCTION_FAQ_FUZZY_MATCH = "find_closest_faq"
SOURCE_FAQ_FUZZY_MATCH = "faq_fuzzy_match"
SOURCE_FAQ_LLM_MATCH = "faq_llm_match"
SOURCE_FAQ_LLM_EVALS = "faq_llm_evals"
SOURCE_ORDER_RETRIEVAL = "retrieve_target_order"
SOURCE_ORDER_INQUIRY = "order_inquiry"
SOURCE_EXCHANGE_RETURN_REASON = "exchange_return_reason"
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
        # Classification, not conversation — low temperature for consistency across near-identical inputs.
        self.order_llm_for_revisit_eval = get_llm(temperature=0.0).with_structured_output(OrderRevisitEval)


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
        shared_instruction = "Focus on: any order(s) mentioned, order number and product name, and what order/ product issue occurred and what actions were taken." \
        "Record the exchange/ return reason if any"
        existing_summary = state.get("summary", "")
        if existing_summary:
            # Extend the existing summary with new messages
            summarize_instruction = (
                f"Current summary:\n{existing_summary}\n\n"
                "Extend this summary with the new messages above. "
                "Keep it under 5 sentences. " + shared_instruction
            )
        else:
            # First time summarising
            summarize_instruction = (
                "Summarise this customer support conversation in under 5 sentences. " + shared_instruction
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
        # Long-term memory is already injected as a SystemMessage in `messages` by
        # invoke_general_support_workflow, and folds into `summary` once summarize_node has
        # run — no need to reach into `messages` by a fixed index for prior context.
        SYSTEM_PROMPT = f"""
        You are an intelligent customer-support agent to help decide if it is helpful to match the customer question
        against FAQs
        Here is the customer's question: {state["general_inquiry"]}.
        Here is FAQ context: {self.faq_context}.
        Here is the summary of the previous conversation if any: {state.get("summary") if state.get("summary") else "None yet"}.
        There are two matching options:
        - Matches with fuzz.partial_ratio scorer of python Rapidfuzz library. The fuzz.partial_ratio process.extractOne finds 
        the single best matching string from choices of FAQ questions for the customer question
        so it favors cases where the customer's question shares a close substring with an FAQ question, even if the
        two differ in length (e.g. extra words before/after).
        - LLM semantic matching
        The above options are NOT mutual exclusive.
        Some context for your reference.  There is a full return policy document.  LLM semantic matching will be given that 
        along with FAQs as the context.  However, I extract the majority of content of the return policy into FAQ's questions and answers that Rapidfuzz partial_ratio can count on too. 
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
            response = f"{PREFIX_ANSWER_QUESTION} {ESCALATE_MESSAGE}"
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
            message = ChatMessage(content=response, role= ROLE_FUNCTION_CALL, name=FUNCTION_FAQ_FUZZY_MATCH, additional_kwargs={
                "faq_match_result": result
            })
            return {
                "messages": [message],
                "response": response,
                "general_issue_resolved": True,
            }
        elif not state["faq_match_evals"].llm_semantic_match_helpful:
            response = f"{PREFIX_ANSWER_QUESTION} {ESCALATE_MESSAGE}"
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
        Here is FAQ context: {self.faq_context}.
        Here is the full return policy {RETURN_POLICY}.  
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
            response = f"{PREFIX_ANSWER_QUESTION} {ESCALATE_MESSAGE}"
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
        # A revisit routes straight here from detect_order_revisit_node, before summarize_node
        # has pruned anything — so the long-term-memory SystemMessage injected by
        # invoke_order_init_workflow can still be sitting in state['messages'] at this point.
        # Keep it in its own labeled section rather than folding it into the raw conversation,
        # same as detect_order_revisit_node.
        memory_notes = "\n".join(
            [f"- {message.content}" for message in state['messages'] if isinstance(message, SystemMessage)]
        )
        recent_conversations = "\n".join(
            [f"- {message.content}" for message in state['messages'] if not isinstance(message, SystemMessage)]
        )
        # Make best use of state['order_is_revisit'] flag
        # Switch to initiate the 'Exchange or return for refund' by the customer.  Separate revisit handling and don't 
        # asssume the escalation unless the confirmation is received.
        # Also make `order_issue_resolved` criteria clearer
        SYSTEM_PROMPT = f"""
            You are an intelligent customer-support agent that helps answer the customer's question regarding to his/ her order.
            Here is the target order {state['target_order'].model_dump_json()}
            {'The customer is revisting the same order' if state['order_is_revisit'] else ''}
            Here is what we remember about this customer from past visits, if any: {memory_notes if memory_notes else "None yet"}.
            Here is the most recent conversations in sequential order: {recent_conversations if recent_conversations else "None yet"}.
            Here is the summary of the previous conversation: {state.get("summary") if state.get("summary") else "None yet"}.
            The above is the context of this order.

            DO NOT REPEAT the same response!! Look for re-visit/ escalate signal!!  
            If the customer is revisting the same order and the prior visit is for a lost shipment and we haven't had recent conversations
            regarding to the lost shipment yet, ask if he/ she has found it and if needs our help.
            (Continued) If we have started recent conversations and he/ she like our help for the lost shipment,  
            set the `escalate` flag to True and set '{ESCALATE_REASON.HELP_LOST_SHIPMENT}' as the `escalate_reason`.
            If the customer is revisting the same order and the prior visit is due to a long 'pending' status and the order is still 'pending'
            and and we haven't had recent conversations for the long 'pending' order, ask if he/ she like to cancel the order.
            (Continued) If we have started recent conversations and he/ she like to cancel the order
            set the `escalate` flag to true and set '{ESCALATE_REASON.HELP_CANCEL_ORDER}' as the `escalate_reason`.
            
            You can wrap up by saying something like 'Can I help you with anything else?' if you find it is at the end of the conversation.
            Set `order_issue_resolved` when the customer reply with an ending signal.
            Return your response for the above.
                                   
            The rest of scenarios that we are trying to cover:
            Find out what the customer is complaining about.
            if the order status is 'delivered' but the customer did not receive the shipment, ask the customer to click the tracking number link to see if there is a delivery photo taken.  
            If yes, is the photo taken in the customer's porch?  If yes, ask the customer to check with his/ her Ring's camera footage if the customer has Ring security system or 
            check with his/ her family members before the customer confirm that the shipment is stolen . UPS would not be responsible for a stolen shipment.  
            If the photo is not taken in the customer's porch or no photo taken, ask the customer to look around the house and/ or check with neighbors.
            Let the customer know that he/ she can always re-visit us after he/ she exhaust searches knowing the shipment is not stolen. 
             
            if the customer is revisiting the same order and complained about item(s) delivered before or
            the customer is complaining about item(s) delivered for any of the following reasons or more
            * Wrong Size or Fit
            * Doesn't Match Description or Photos
            * Damaged or Defective
            * Changed Mind or Impulse Buy
            * Late Delivery
            * Wrong Item   
            Tell the customer he/ she can press 'Intend to Exchange or Return for Refund' button if he/ she want to do that and we will help the process.

            if the order status is 'transit', ask the customer to track the whereabouts of the shipping using the UPS's tracking number.
            if the order status is 'pending', let him/ her know that the order should be fulfilled no later than {(state['target_order'].order_date + timedelta(days= 7)).isoformat()} (within 7 days).  
            The customer can always call back by then to cancel the order.
            if the customer like to cancel the order now, you should set the `escalate` flag to true and set '{ESCALATE_REASON.HELP_CANCEL_ORDER}' as the `escalate_reason`

            The customer-support agent app currently is not supporting checking the return refund status of a specific order.  Delegate it to human customer-support representative
            by setting the `escalate` flag to true and set '{ESCALATE_REASON.HELP_CHECK_RETURN_REFUND_STATUS}' as the `escalate_reason`

            If the customer ask a general inquiry not related to his/ her recent order, ask him/ her to click 'general inquiry' button. The agent there 
            will be happy to help.

            if the customer's conversation lead to an uncovered scenario or that you do not have an answer, please set `escalate` flag to True and set
            '{ESCALATE_REASON.HELP_ANSWER_ORDER_INQUIRY}' as the `escalate_reason`

            set `response` to what you want to reply 
            """
            # It's possible that the customer also ask some 'general inquiry', will direct the customer to click 'general inquiry' button for now. 
            # Try not to use too many tokens
        
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        logger.info("order_continue_chat_node prompt for order #%s:\n%s", state['order_number_provided'], SYSTEM_PROMPT)
        order_output: OrderStructuredOutput = await self.order_llm_for_inquiry_chat.ainvoke([system_msg])
        logger.info("order_continue_chat_node result for order #%s: %s", state['order_number_provided'], order_output)
        # mock llm will return order_output None
        if not order_output or order_output.escalate:
            escalation_reason = order_output.escalation_reason if order_output else ESCALATE_REASON.HELP_ANSWER_ORDER_INQUIRY
            prefix = ""
            match escalation_reason:
                case ESCALATE_REASON.HELP_LOST_SHIPMENT:
                    prefix = PREFIX_LOST_SHIPMENT
                case ESCALATE_REASON.HELP_CANCEL_ORDER:
                    prefix = PREFIX_CANCEL_ORDER
                case ESCALATE_REASON.HELP_CHECK_RETURN_REFUND_STATUS:
                    prefix = PREFIX_CHECK_RETURN_REFIND_STATUS    
                case _:
                    prefix = PREFIX_ANSWER_QUESTION
            response = f"{prefix} {ESCALATE_MESSAGE}"                
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                    "source": SOURCE_ORDER_INQUIRY})
            return {
                "messages": [message],
                "response": response,
                "escalation_reason": f"{escalation_reason} of order #{state['order_number_provided']}",
                "order_issue_escalated": True,               
            }
                        
        message = AIMessage(content= order_output.response, additional_kwargs={
                "source":SOURCE_ORDER_INQUIRY})            
        return {
            "messages": [message],
            "response": order_output.response,
            "order_issue_resolved": order_output.order_issue_resolved, # signal writing the summary
        }

    # Preparation only: retrieve the order and set it on state. Deliberately separate from
    # response generation below, so the routing decision (static template vs. revisit-aware
    # LLM handoff) sits between retrieval and rendering rather than being baked into one node.
    async def retrieve_target_order_node(self, state: CustomerSupportState) -> dict[str, Any]:
        target_order: Order = retrieve_target_order(state["customer_context"], state["order_number_provided"])
        if target_order:
            return {"target_order": target_order}
        # It should not happen
        response = SYSTEM_ERROR_MESSAGE
        message = ChatMessage(content=response, role= ROLE_AGENT, additional_kwargs= {"source": SOURCE_ORDER_RETRIEVAL})
        return {
            "target_order": None,
            "messages": [message],
            "response": response,
        }

    # Decides whether this order_number_provided has already been discussed (this thread's
    # running summary, or long-term memory injected into `messages` for a brand-new thread) —
    # as opposed to genuinely being raised for the first time. Uses LLM judgement rather than a
    # string/substring match against the order number, since the summary may refer to the order
    # by product name ("your PowerBank order") without repeating the numeric id.
    async def detect_order_revisit_node(self, state: CustomerSupportState) -> dict[str, Any]:
        target_order = state["target_order"]
        # invoke_order_init_workflow injects long-term memory as a SystemMessage — keep it in its
        # own labeled section rather than folding it into the raw conversation transcript, so the
        # classifier doesn't have to infer which lines are "known history" vs. this turn's message.
        memory_notes = "\n".join(
            [f"- {message.content}" for message in state["messages"] if isinstance(message, SystemMessage)]
        )
        recent_conversations = "\n".join(
            [f"- {message.content}" for message in state["messages"] if not isinstance(message, SystemMessage)]
        )
        product_names = [f"'{item.product_name}'" for item in target_order.items]
        
        SYSTEM_PROMPT = f"""
        You are an intelligent customer-support agent trying to decide whether the customer has already
        discussed order #{target_order.order_id} in a prior conversation, as opposed to raising it for the
        very first time just now.
        Here is the summary of this conversation thread so far, if any: {state.get("summary") if state.get("summary") else "None yet"}.
        Here is what we remember about this customer from past visits, if any: {memory_notes if memory_notes else "None yet"}.
        Here is the most recent conversation in this thread, in sequential order: {recent_conversations if recent_conversations else "None yet"}.
        Set `is_revisit` to True only if there is clear evidence order #{target_order.order_id} or products ordered: {"or ".join(product_names)} specifically
        (not just any order) was already discussed — for example a prior mention of a lost shipment, a
        return/ refund request, a cancellation, or any other support issue tied to this order.
        Set `is_revisit` to False if this looks like the first time the customer is raising this order, or if
        you are not sure.
        """
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        logger.info("detect_order_revisit_node prompt for order #%s:\n%s", target_order.order_id, SYSTEM_PROMPT)
        eval: OrderRevisitEval = await self.order_llm_for_revisit_eval.ainvoke([system_msg])
        logger.info("detect_order_revisit_node result for order #%s: %s", target_order.order_id, eval)
        return {"order_is_revisit": bool(eval and eval.is_revisit)}

    # Fresh-inquiry path only: deterministic, no LLM call, assumes retrieve_target_order_node
    # already populated `target_order` and detect_order_revisit_node found no prior conversation
    # about it. A revisit skips this node entirely and goes straight to order_continue_chat_node.
    async def order_init_static_response_node(self, state: CustomerSupportState) -> dict[str, Any]:
        target_order = state["target_order"]
        response = ""
        # ["delivered", "transit", "pending"]
        match target_order.status:
            case "pending":
                response = f"Your order is still in 'pending' status. You order on {target_order.order_date}. "
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
            "messages": [message],
            "response": response,
        }

    ##########################################################################
    #       Exchange or return survey, assume no interaction is needed
    ##########################################################################
    # This is not a chat screen and do have buttons to direct to other screen, including 'start a return refund'. Design a static response
    # for now.
    def get_recommended_action(self, reason: ExchangeOrReturnInput) -> tuple[ExchangeReturnReason, ExchangeReturnRefundAction] :
        if reason:
            match reason.reason_option:
                case ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS | ExchangeReturnReason.WRONG_ITEM_SHIPPED:
                    return reason.reason_option, ExchangeReturnRefundAction.EXPEDITE_EXCHANGE
                case ExchangeReturnReason.BETTER_PRICE_FOUND:
                    return reason.reason_option, ExchangeReturnRefundAction.PARTIAL_REFUND
                case ExchangeReturnReason.WRONG_SIZE_OR_FIT | ExchangeReturnReason.DIFFERENT_COLOR_OR_STYLE:
                    return  reason.reason_option, ExchangeReturnRefundAction.EXCHANGE
                case _:
                    return reason.reason_option, ExchangeReturnRefundAction.RETURN

        return None, ExchangeReturnRefundAction.RETURN        

    async def exchange_return_reason_recommendation_node(self, state: CustomerSupportState) -> dict[str, Any]:
        # Will validate at the service level
        reason, action = self.get_recommended_action(state['exchange_return_reason'])
        if action == ExchangeReturnRefundAction.EXPEDITE_EXCHANGE:
            if reason == ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS:
                prefix = f'{PREFIX_RCVD_DAMAGED_PRODUCT} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}'
            else:
                prefix = f'{PREFIX_RCVD_WRONG_ITEM} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}'
            response = f"{prefix} {ESCALATE_MESSAGE}"                
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                    "source": SOURCE_EXCHANGE_RETURN_REASON})
            return {
                "messages": [message],
                "response": response,
                "escalation_reason": f"{ESCALATE_REASON.HELP_EXPEDITE_EXCHANGE_FOR_DEFECTIVE_WRONG_ITEM} of order #{state['order_number_provided']}",       
            }
        elif action == ExchangeReturnRefundAction.PARTIAL_REFUND:
            prefix = PREFIX_FOUND_BETTER_PRICE
            response = f"{prefix} {ESCALATE_MESSAGE}"                
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                    "source": SOURCE_EXCHANGE_RETURN_REASON})
            return {
                "messages": [message],
                "response": response,
                "escalation_reason": f"{ESCALATE_REASON.HELP_DECIDE_IF_PRICE_MATCH_WITH_COMPETITOR} of order #{state['order_number_provided']}",       
            }
        elif action == ExchangeReturnRefundAction.EXCHANGE:
            response = f"""We recommend 'exchange' since you want a different size, color or style. 
            Go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange.
            You can come back here to press “Start return for refund process” button if we are unable to find an suitable item to exchange with. 
            """
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_EXCHANGE_RETURN_REASON})
            return { "messages": [message], "response": response}
        else: # return
            response = f"""We recommend 'Return' based upon the reason you provided. Press “Start return for refund process” button to initiate.
            However, if you have a purchase item in your mind and like to take advantage of a return shipping label we offer for an exchange,   
            just go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange instead."""
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_EXCHANGE_RETURN_REASON})
            return { "messages": [message], "response": response}
                        

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
            case "exchange_or_return":
                return "exchange_or_return"
            case _:
                return self.route_order(state)       

    # It's not an actual route. It return node by condition.  Get around with conditional edge within conditional edge
    def route_order(self, state: CustomerSupportState) -> str:
        # Fix an error if order_number not passed or passed as 0.  Let retrieve_target_order instead of order_continue_chat_node handle
        if not state.get("target_order"):
            return "order_init"

        return "order_init_done"

    def route_after_retrieve_target_order(self, state: CustomerSupportState) -> str:
        if not state.get("target_order"):
            # retrieve_target_order_node already built the SYSTEM_ERROR_MESSAGE response
            return "summarize_node"
        return "detect_order_revisit_node"

    def route_after_detect_order_revisit(self, state: CustomerSupportState) -> str:
        if state.get("order_is_revisit"):
            return "order_continue_chat_node"
        return "order_init_static_response_node"

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
        if self._should_summarize(state, state.get("order_issue_escalated") or state.get("order_issue_resolved")):
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
                                       "exchange_or_return": "exchange_return_reason_recommendation_node",
                                       "order_init": "retrieve_target_order_node",
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

        builder.add_node("retrieve_target_order_node", self.retrieve_target_order_node)
        builder.add_conditional_edges("retrieve_target_order_node", self.route_after_retrieve_target_order,
            {"summarize_node": "summarize_node", "detect_order_revisit_node": "detect_order_revisit_node"})

        builder.add_node("detect_order_revisit_node", self.detect_order_revisit_node)
        builder.add_conditional_edges("detect_order_revisit_node", self.route_after_detect_order_revisit,
            {"order_init_static_response_node": "order_init_static_response_node", "order_continue_chat_node": "order_continue_chat_node"})

        builder.add_node("order_init_static_response_node", self.order_init_static_response_node)
        # It's not cost effcient to inject order_continue_chat_node with long-term memory every time it was invoke.
        # Instead, I summarize here and include the content long-term memory so that 'order_continue_chat_node' has a good context
        builder.add_edge("order_init_static_response_node", "summarize_node")

        builder.add_conditional_edges("order_continue_chat_node", self.route_after_order_continue_chat,
            {"summarize_node": "summarize_node", END: END})

        builder.add_node("exchange_return_reason_recommendation_node", self.exchange_return_reason_recommendation_node)
        builder.add_edge("exchange_return_reason_recommendation_node", "summarize_node")
        
        graph = builder.compile(checkpointer = self.checkpointer, store = self.store)
        self.graph = graph
        return graph
    

    