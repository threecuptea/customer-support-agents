from __future__ import annotations
from models.model import ChatState, FAQMatchEvals, FAQMatchResult, Order

from langgraph.graph import END, START, StateGraph
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from typing import Any
from dotenv import load_dotenv
import logging
import os
from workflow.llm import get_llm
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_store
from memory import save_user_memory
from workflow.customer_support_tools \
import find_closest_faq, calculate_amount_refund_incl_tax, retrieve_target_order, check_if_refund_require_manual_approval, \
    get_next_order_available, faq_dict
from langgraph.prebuilt import ToolNode


load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

FAQ_MATCH_THRESHOLD = 70.0
ESCALATE_MESSAGE = "I will escalate to a human agent and somebody will contact you within 3 business days"


class CustomerSupportAgent:
    def __init__(self, checkpointer, store):
        self.checkpointer = checkpointer
        self.store = store
        # I can override model and provider to use overrides if needed
        self.summarize_llm = get_llm()
       
        # FAQ matching
        self.general_llm_for_faq_match_evals = get_llm().with_structured_output(FAQMatchEvals)
        self.general_llm_for_faq_match_result = get_llm().with_structured_output(FAQMatchResult)
    
        # "\n".join(f"- {n}" for n in notes)
        self.faq_context = "\n".join([f"- 'question': {key}, 'answer': {val} " for key, val in faq_dict])


    ###############################################
    #               Summarize Node
    ###############################################
    # Borrow from https://pub.towardsai.net/your-first-real-langgraph-project-ac5eb00f923a              
    async def summarize_node(self, state: ChatState, config: RunnableConfig) -> dict[str, Any]:
        """Triggered when the conversation exceeds 6 messages. Compresses the
        full message history into a short summary, then deletes old raw messages.
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
        await save_user_memory(self.store, state.customer_context.customer_id, thread_id, response.content)

        return {
            "summary": response.content,
            "messages": messages_to_delete,
        }

    ###############################################
    #               General Nodes
    ###############################################
    # I might need to 
    async def general_faq_eval_node(self, state: ChatState) -> dict[str, Any]:
        # TODO: Find an example of comprehensive e-commerce policy to replace FAQs to match against
        # FAQs is to enlist most commonly asked questions.  There should be a comprehensive company policy to cover all possible causes.

        SYSTEM_PROMPT = f"""
        You are an intelligent customer-support agent to help decide if it is helful to match the customer question 
        against FAQs
        Here is the customer's question: {state["messages"][-1].content}.
        Here are FAQ context: {self.faq_context}.
        There are two matching options: 
        - Matches with fuzz.WRatio scorer of python Rapidfuzz library. The fuzz.WRatio scorer weights and combines multiple strategies 
        such as case variations, substring checks, and token ordering
        - LLM semantic matching
        The above options are not mutual exclusive.
        Set `rapid_fuzz_wratio_match_helpful` if you think that the fuzz match option will be helpful.
        Set `llm_semantic_match_helpful` if you think the LLM semantic match will be help.
        state `reason` as needed. 
        The followings are brief explanation of fuzz.WRatio for your reference:

        1. Take the ratio of the two processed strings (fuzz.ratio)
        2. Run checks to compare the length of the strings
            * If one of the strings is more than 1.5 times as long as the other
            use partial_ratio comparisons - scale partial results by 0.9
            (this makes sure only full results can return 100)
            * If one of the strings is over 8 times as long as the other
            instead scale by 0.6
        3. Run the other ratio functions
            * if using partial ratio functions call partial_ratio,
            partial_token_sort_ratio and partial_token_set_ratio
            scale all of these by the ratio based on length
            * otherwise call token_sort_ratio and token_set_ratio
            * all token based comparisons are scaled by 0.95
            (on top of any partial scalars)
        4. Take the highest value from these results round it and return it as an integer.
        """
        # Do I use Mesage the right way.  
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        # resp should an AIMessage wrapper
        # FAQMatchEvals
        eval = await self.general_llm_for_faq_match_evals.ainvoke([system_msg])
        updates = {"general_inquiry": {state["messages"][-1].content}, "faq_match_evals": eval}
        if not eval or (eval and not eval.rapid_fuzz_wratio_match_helpful and not eval.llm_semantic_match_helpful):
            response = ESCALATE_MESSAGE
            message = SystemMessage(content=response)
            updates["messages"] = [message]
            updates["response"] = response
            updates["general_issue_resolved"] = True
            
        return updates

    
    # I don't like to use ToolNode, Yes, it would know the latest AI message, 
    # runs the matching functions (often at the same time), and turns the results into tool messages
    # However, ToolMessage content is always string.  I don't like to convert BaseModel to str then 
    # convert str to BaseModel back and forth.  I want it to return a BaseModel as it is
    async def general_faq_fuzz_match_node(self, state: ChatState) -> dict[str, Any]:
        result: FAQMatchResult = find_closest_faq(state["general_inquiry"])  
        if result and result.confidence_score >= FAQ_MATCH_THRESHOLD:
            response = result.answer
            message = ToolMessage(content=response, name="find_closest_faq")
            return {
                "messages": [message],
                "response": response,
                "general_issue_resolved": True,
            }
        elif not state["faq_match_evals"].llm_semantic_match_helpful:
            response = ESCALATE_MESSAGE
            message = SystemMessage(content=response)
            return {
                    "messages": [message],
                    "response": response,
                    "general_issue_resolved": True,
            }
        else:
            return {
            }

    async def general_faq_llm_match_node(self, state: ChatState) -> dict[str, Any]:
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
            message = AIMessage(content=response)
            return {
                "messages": [message],
                "response": response,
                "general_issue_resolved": True,
            }
        else:
            response = ESCALATE_MESSAGE
            message = SystemMessage(content=response)
            return {
                    "messages": [message],
                    "response": response,
                    "general_issue_resolved": True,
            }


    ###############################################
    #               Order Nodes
    ###############################################
    
    async def order_inquiry_node(self, state: ChatState) -> dict[str, Any]:
        # This should be a node to use 'retrieve_target_order' tool
        # need adjustment by AI what if a repeated conversation
        if not state["target_order"] and state["order_number_provided"]:
            target_order: Order = retrieve_target_order(state["customer_context"], state["order_number_provided"])
            if not target_order:
                # It should be be since it comes from CustomerContext that we retrieve.
                raise ValueError(f"Unexpected error: unable to retrieve the target order: {state["order_number_provided"]}")
        response = ""
        # If no previous conversation
        match target_order.status:
            case "pending": 
                response = "Your order is still in 'pending' status. "
                if target_order.notes:
                    response += f"Notes say: {target_order.notes}. "
                else:
                    response += "Notes does not tell me additional information. "    
                response += "We will ship as soon as the order is ready." 
            case "transit":
                response = f"Your order is still in 'transit' status. it was estimated to arrive at {target_order.estimated_delivery_date.isoformat()}. "
                 
       
            
    ###############################################
    #            Routes after a node
    ###############################################
    def route_branch(self, state: ChatState) -> str:
        # Speed up the workflow and let UI take care
        # What if the customer ask general questions (possible different ones) more than once?  Should we execute more than once
        # For order, will branch out based upon if target_order is set and if return_refund_eligible is set and if intent_for_return_refund etc.
        match state.support_category:
            case "general/ others":
                return "general_faq_eval_node"
            case _:
                return "order_inquiry_node"
        return ""       

    def route_after_general_faq_eval(self, state: ChatState) -> str:      
        if state["general_issue_resolved"]:
            return END
        if state["faq_match_evals"]:
            if state["faq_match_evals"].rapid_fuzz_wratio_match_helpful:
                return "general_faq_fuzz_match_node"
            if state["faq_match_evals"].llm_semantic_match_helpful:
                return "general_faq_llm_match_node" 
        return END

    def route_after_general_faq_fuzz_match(self, state: ChatState) -> str:      
        if state["general_issue_resolved"]:
            return END
        return "general_faq_llm_match_node"

    


    ###############################################
    #            Build the support graph
    ###############################################
    def build_support_graph(self):
        """Build and compile the main chat/ refund workflow."""
        builder = StateGraph(ChatState)
        # Harnese with RetryPolicy later
        '''case "others":
                        return "general_faq_eval_node"
                    case _:
                        return "order_retrieve_target_order_node"
        '''                   
        builder.add_conditional_edges(START, self.route_branch, 
                                      {"general_faq_eval_node": "general_faq_eval_node", 
                                       "order_retrieve_target_order_node": "order_retrieve_target_order_node"})
        
        builder.add_node("summarize_node", self.summarize_node)
        builder.add_edge("summarize_node", END)

        
        builder.add_node("general_faq_eval_node", self.general_faq_eval_node)
        builder.add_conditional_edges("general_faq_eval_node", self.route_after_general_faq_eval,
            {END: END, "general_faq_fuzz_match_node": "general_faq_fuzz_match_node", "general_faq_llm_match_node": "general_faq_llm_match_node"})

        builder.add_node("general_faq_fuzz_match_node", self.general_faq_fuzz_match_node)
        builder.add_conditional_edges("general_faq_fuzz_match_node", self.route_after_general_faq_fuzz_match,
            {END: END, "general_faq_llm_match_node": "general_faq_llm_match_node"})
        
        builder.add_node("general_faq_llm_match_node", self.general_faq_llm_match_node)
        builder.add_edge("general_faq_llm_match_node", "summarize_node")

        builder.add_node("order_inquiry_node", self.order_inquiry_node)
        
        return builder.compile(cheeckpointer = self.checkpointer, store = self.store)
    

    