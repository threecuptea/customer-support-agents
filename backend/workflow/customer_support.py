from __future__ import annotations
from models.model import CustomerSupportState, FAQMatchEvals, FAQMatchResult, Order, OrderStructuredOutput,\
    ESCALATE_REASON, OrderRevisitEval, ExchangeReturnRefundAction, ExchangeReturnReason, ExchangeOrReturnInput, OrderToReturn, OrderRefundStatus, \
    ReturnRefundStructuredOutput

from langgraph.graph import END, START, StateGraph
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage, AIMessage, ChatMessage
from typing import Any
from dotenv import load_dotenv
import logging
import os
from workflow.llm import get_llm
from langchain_core.runnables import RunnableConfig
from datetime import timedelta
from workflow.order_situation import select_order_situation, render_situation_text, escalation_allowed, ALWAYS_ON_TEXT
import copy
from memory import save_user_memory
from workflow.customer_support_utils import find_closest_faq, retrieve_target_order, faq_dict, RETURN_POLICY, \
    get_initial_return_refund_decision, threshold_amount_auto_approve, threshold_days_auto_approve

from workflow.return_refund_utils import ThreadSafeCounter, refund_requests_processing_dict 


load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

SUMMARIZE_MESSAGE_THRESHOLD = 6
FAQ_MATCH_THRESHOLD = 75.0
ESCALATE_MESSAGE = "I will escalate your inquiry/ request to a human agent and somebody will contact you within 3 business days."
SYSTEM_ERROR_MESSAGE = "System error!! We cannot find your order, please try it later"
ESCALATE_REASON_FAQ = "Unable to find a satifactory answer to the customer's question"

PREFIX_ANSWER_QUESTION = "I don't have an answer to your question."
PREFIX_LOST_SHIPMENT = "You need help to handle your lost shipment."
PREFIX_CANCEL_ORDER = "You need help to cancel your order."
PREFIX_CHECK_RETURN_REFIND_STATUS = "You need help to check the return refund status of your order."
PREFIX_NEED_EXPEDIT_REPLACEMENT = "need to expedite a replacement."
PREFIX_RCVD_DAMAGED_PRODUCT = "You received broken or defective items or a product with missing parts"
PREFIX_RCVD_WRONG_ITEM = "You received an wrong item"
PREFIX_FOUND_BETTER_PRICE = "You found that our competitor offer a better price and we like to see if we can price match that."
SUFFIX_RCVD_DAMAGED_WRONG_ITEM = "A photo of proof might be required."

FUNCTION_FAQ_FUZZY_MATCH = "find_closest_faq"
FUNCTION_GET_INITIAL_DECISION = "get_initial_return_refund_decision"
SOURCE_FAQ_FUZZY_MATCH = "faq_fuzzy_match"
SOURCE_FAQ_LLM_MATCH = "faq_llm_match"
SOURCE_FAQ_LLM_EVALS = "faq_llm_evals"
SOURCE_ORDER_RETRIEVAL = "retrieve_target_order"
SOURCE_ORDER_INQUIRY = "order_inquiry"
SOURCE_EXCHANGE_RETURN_REASON = "exchange_return_reason"
SOURCE_RETURN_REFUND_PROCESS = "return_refund_process"
SOURCE_RETURN_REFUND_CHAT = "return_refund_chat"
ROLE_FUNCTION = "function"
ROLE_AGENT = "assistant"

DEFAULT_CHAT_NODE_MODEL = "gpt-4.1"


def _flow(text: str) -> str:
    """Collapse the newlines/indentation a multi-line triple-quoted string picks up from the
    source layout, so static customer-facing text renders as one clean paragraph (the UI uses
    `whitespace-pre-wrap`, which would otherwise show those indents literally)."""
    return " ".join(text.split())

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
        # The two free-form chat nodes (order_continue_chat_node, return_refund_chat_node) follow many
        # competing rules in one prompt and are the most model-sensitive (CSA-18 harness), so they use a
        # stronger model than the rest. Override with CHAT_NODE_MODEL; read here, at construction time.
        self.chat_node_llm = get_llm(model=os.getenv("CHAT_NODE_MODEL", DEFAULT_CHAT_NODE_MODEL))
        self.order_llm_for_inquiry_chat = self.chat_node_llm.with_structured_output(OrderStructuredOutput)
        # Classification, not conversation — low temperature for consistency across near-identical inputs.
        self.order_llm_for_revisit_eval = get_llm(temperature=0.0).with_structured_output(OrderRevisitEval)
        self.return_refund_llm = self.chat_node_llm.with_structured_output(ReturnRefundStructuredOutput)

        self.return_refund_counter = ThreadSafeCounter(initial_value = 1000)

        
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
            message = ChatMessage(content=response, role= ROLE_FUNCTION, name=FUNCTION_FAQ_FUZZY_MATCH, additional_kwargs={
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
        logger.info(f"order_continue_chat_node beginning state for order #{state['order_number_provided']}:\nmemory notes: {memory_notes}\nrecent conversations: {recent_conversations}")
        # Code decides the ONE situation that applies (CSA-19); only that situation's text reaches the LLM,
        # so a rule written for one situation cannot contradict or shift the behaviour of another.
        target_order = state['target_order']
        turns = state.get("order_turns", 0)
        situation = select_order_situation(
            status=target_order.status, is_revisit=bool(state.get('order_is_revisit')),
            prior_topic=state.get("order_prior_topic"), turns=turns)
        situation_text = render_situation_text(
            situation,
            deadline=(target_order.order_date + timedelta(days=7)).isoformat(),
            tracking=str(target_order.tracking_number or ""),
            delivered_on=target_order.delivery_date.isoformat() if target_order.delivery_date else "an unknown date",
        )
        # The situation texts name the escalation reasons by member name; give the LLM the exact values.
        always_on_text = ALWAYS_ON_TEXT
        for reason in ESCALATE_REASON:
            situation_text = situation_text.replace(reason.name, f"'{reason.value}'")
            always_on_text = always_on_text.replace(reason.name, f"'{reason.value}'")
        latest_message = next((m.content for m in reversed(state['messages']) if isinstance(m, HumanMessage)), "")
        logger.info("order_continue_chat_node situation for order #%s: %s (turns=%s)", state['order_number_provided'], situation, turns)
        SYSTEM_PROMPT = f"""
            You are an intelligent customer-support agent that helps answer the customer's question regarding to his/ her order.
            Here is the target order {target_order.model_dump_json()}
            Here is what we remember about this customer from past visits, if any: {memory_notes if memory_notes else "None yet"}.
            Here is the most recent conversations in sequential order: {recent_conversations if recent_conversations else "None yet"}.
            Here is the summary of the previous conversation: {state.get("summary") if state.get("summary") else "None yet"}.
            The above is the context of this order.

            CURRENT SITUATION (the only situation-specific instructions that apply): {situation_text}

            Rules that always apply: {always_on_text}

            The customer's latest message is: {latest_message}
            Set `response` to what you want to reply.
            """

        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        order_output: OrderStructuredOutput = await self.order_llm_for_inquiry_chat.ainvoke([system_msg])
        logger.info("order_continue_chat_node structured output for order #%s: %s", state['order_number_provided'], order_output)
        # mock llm will return order_output None
        if order_output and order_output.escalate and not escalation_allowed(
                order_output.escalation_reason, situation, target_order.status):
            # Code veto: an escalation that cannot apply to this order/ situation is a model slip, answer normally.
            logger.warning("order_continue_chat_node vetoed escalation %s in situation %s", order_output.escalation_reason, situation)
            order_output.escalate = False
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
                "order_turns": state.get("order_turns", 0) + 1,
            }
                        
        message = AIMessage(content= order_output.response, additional_kwargs={
                "source":SOURCE_ORDER_INQUIRY})            
        return {
            "messages": [message],
            "response": order_output.response,
            "order_issue_resolved": order_output.order_issue_resolved, # signal writing the summary
            "order_turns": state.get("order_turns", 0) + 1,
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
        logger.info(f"detect_order_revisit_node beginning state for order #{state['order_number_provided']}:\nmemory notes: {memory_notes}\nrecent conversations: {recent_conversations}")

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
        If (and only if) `is_revisit` is True, also set `prior_topic` to what the earlier discussion of THIS order was about:
        - 'lost_shipment': the order showed as delivered but the package never arrived, or the shipment was reported lost, stolen or missing.
        - 'pending_cancel': the order was pending a long time and had not shipped, or the customer asked about cancelling it.
        - 'other': anything else (for example a return or refund, a damaged or wrong item, a question about shipping or delivery dates).
        If `is_revisit` is False, leave `prior_topic` empty.
        """
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        eval: OrderRevisitEval = await self.order_llm_for_revisit_eval.ainvoke([system_msg])
        logger.info("detect_order_revisit_node structured output for order #%s: %s", target_order.order_id, eval)
        is_revisit = bool(eval and eval.is_revisit)
        # A prior topic only makes sense for a revisit; ignore one the LLM gave without it.
        prior_topic = eval.prior_topic if is_revisit else None
        return {"order_is_revisit": is_revisit, "order_prior_topic": prior_topic}

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
    #   Exchange or return reason survey, assume no interaction is needed
    ##########################################################################
    # This is not a chat screen and do have buttons to direct to other screen, including 'start a return refund'. Design a static response for now
    def get_recommended_action(self, reason: ExchangeOrReturnInput) -> tuple[ExchangeReturnReason, ExchangeReturnRefundAction] :
        # In the real word, reason.reason_option and reason.reason_input should be persisted.
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
        reason, action = self.get_recommended_action(state.get('exchange_return_reason'))
        if action == ExchangeReturnRefundAction.EXPEDITE_EXCHANGE:
            if reason == ExchangeReturnReason.DAMAGED_DEFECTIVE_OR_MISSING_PARTS:
                prefix = f'{PREFIX_RCVD_DAMAGED_PRODUCT} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}'
            else:
                prefix = f'{PREFIX_RCVD_WRONG_ITEM} and {PREFIX_NEED_EXPEDIT_REPLACEMENT}'
            response = f"{prefix} {ESCALATE_MESSAGE} {SUFFIX_RCVD_DAMAGED_WRONG_ITEM}"                
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                    "source": SOURCE_EXCHANGE_RETURN_REASON})
            return {
                "special_exchange_handling": True,
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
            response = _flow(f"""We recommend 'exchange' since you want a different size, color or style. 
            Go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange.
            You can come back here to press “Start return for refund process” button if we are unable to find an suitable item to exchange for. 
            """)
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_EXCHANGE_RETURN_REASON})
            return { "messages": [message], "response": response}
        else: # return
            response = _flow(f"""We recommend 'Return' based upon the reason you provided. Press “Start return for refund process” button to initiate.
            However, if you have a purchase item in your mind and like to take advantage of a return shipping label we offer for an exchange,   
            just go to e-shopping.com, look for Support -> Echange on the top of the screen then follow the instruction to initiate an exchange instead.""")
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_EXCHANGE_RETURN_REASON})
            return { "messages": [message], "response": response}
                        

    ##########################################################################
    #   Return refund process
    ##########################################################################
    async def initial_return_refund_decision_node(self, state: CustomerSupportState) -> dict[str, Any]:
        order_to_return: OrderToReturn = state["order_to_return"]
        target_order: Order = state["target_order"]
        refund_request, initial_decision = get_initial_return_refund_decision(order_to_return, target_order)
        messages = []
        
        if refund_request:
            messages.append(ChatMessage(content=initial_decision.order_refund_status.value, role= ROLE_FUNCTION, name=FUNCTION_GET_INITIAL_DECISION, 
                additional_kwargs={
                "return_order": target_order.order_id, "return_item": order_to_return.items}))
            match initial_decision.order_refund_status:
                case OrderRefundStatus.ORDER_AUTO_REFUNDABLE:
                    response = "Congratulations!! It's in my authority to approve your request."
                case OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT:
                    response = _flow(f"""It's not in my authority to approve your request because the refund amount before tax has exceeded my authorized amount threshold: ${threshold_amount_auto_approve}.
                    Your request requires a manual approval and the request details can be sent to a Slack app channel and an on-duty customer support representative
                    can approve it shortly.
                    """)
                # don't automatically offer a escalate human review unless the customer insist
                case OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS:
                    response = _flow(f"""
                    I am sorry that I have to reject your return refund request because your request come too late and has passed {threshold_days_auto_approve} days of the return window deadline.
                    """)
                case OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS:
                    response = _flow(f"""
                    I am sorry that I have to reject your return refund request because you are trying to return a non-refundable item.
                    """)
            response += " Press 'Process the request' to proceed based on the initial decision, press 'Cancel' to cancel the request or press 'I like to chat' to chat for a futher discussion"        
            return {
                "response": response, 
                "messages": messages, 
                "initial_return_refund_decision": initial_decision, 
                "refund_request_to_process": refund_request,
                }

        messages.append(ChatMessage(content=initial_decision.order_refund_status.value, role= ROLE_FUNCTION, name=FUNCTION_GET_INITIAL_DECISION))
        return {
            "response": initial_decision.order_refund_status.value, 
            "messages": messages, 
            "initial_return_refund_decision": initial_decision, 
            "refund_request_to_process": None,
        }

    async def return_refund_process_node(self, state: CustomerSupportState) -> dict[str, Any]:    
        temp_request = copy.deepcopy(state["refund_request_to_process"])
        initial_decision = state["initial_return_refund_decision"]
        response = ""
        match initial_decision.order_refund_status:
            case OrderRefundStatus.ORDER_AUTO_REFUNDABLE:
                temp_request.status = 'auto_approve'
                temp_request.decided_by = 'Agent'
                temp_request.decided_date = temp_request.request_date
                response = "You would receive a confirmation email with instructions on how and where to send your package."
            case OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS | OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS:
                reason = "the request has passed the return window deadline." if initial_decision.order_refund_status == OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS else \
                "the request includes a non-refundable item."
                if state.get("notes_for_human_review_override"):
                    temp_request.status = 'wait_for_manual_review'
                    temp_request.requires_manual_approval = True
                    temp_request.requires_manual_approval_reason = reason
                    temp_request.notes_for_human_review_override = state["notes_for_human_review_override"]
                    response = "You would receive an email of a human review result regarding to your refund request shortly. " \
                        "If approved, Your email will have the instructions on how and where to send your package."
                else:    
                    temp_request.status = 'auto_reject'
                    temp_request.decided_by = 'Agent'
                    temp_request.decided_date = temp_request.request_date
                    temp_request.decision_reason = reason
                    response = "You would receive a rejection email and detail the underlined reason."
            case OrderRefundStatus.ORDER_HUMAN_REFUNDABLE_DUE_TO_AMOUNT:
                temp_request.status = 'wait_for_manual_review'
                temp_request.requires_manual_approval = True
                temp_request.requires_manual_approval_reason = "the request exceeds the automatic authorized refund amount"
                response = "You would receive an email of a human review result regarding to your refund request shortly. " \
                    "If approved, Your email will have the instructions on how and where to send your package."
            case _:
                return {}
        assigned_refund_request_id = self.return_refund_counter.increment()
        temp_request.refund_request_id = assigned_refund_request_id
        refund_requests_processing_dict[assigned_refund_request_id] = temp_request
        message = ChatMessage(content=response, role= ROLE_AGENT, additional_kwargs={"source": SOURCE_RETURN_REFUND_PROCESS})
        
        return {
            "response": response,
            "messages": [message],
            "assigned_refund_request_id" : assigned_refund_request_id,
            "refund_request_to_process": temp_request
        }
            
    async def return_refund_chat_node(self, state: CustomerSupportState) -> dict[str, Any]:
        memory_notes = "\n".join(
            [f"- {message.content}" for message in state['messages'] if isinstance(message, SystemMessage)]
        )
        recent_conversations = "\n".join(
            [f"- {message.content}" for message in state['messages'] if not isinstance(message, SystemMessage)]
        )
        logger.info(f"return_refund_chat_node beginning state for order #{state['order_number_provided']}, assigned_refund_request_id={state['assigned_refund_request_id']}:\nmemory notes: {memory_notes}\nrecent conversations: {recent_conversations}\nsummary: {state.get('summary') if state.get('summary') else 'None yet'}")
        refund_request = state["refund_request_to_process"]
        decision = state["initial_return_refund_decision"]
        processed = (state.get("assigned_refund_request_id") or 0) > 0
        review_requested = bool(state.get("request_human_review_return_refund"))
        rejected_by_agent = decision.order_refund_status in (
            OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS)
        if processed and refund_request.status == "wait_for_manual_review":
            situation = (
                "The request has ALREADY been processed and a human review has ALREADY been requested and submitted; it is with a human reviewer now. "
                "Facts for questions about this request's status, decision, human review or next steps: the customer will receive an email once the review is done, "
                "usually within 15 minutes and no more than 30 minutes (the app is integrated with Slack so an on-duty representative is notified). "
                "Rules: NEVER offer or ask about a human review, NEVER ask the customer to write notes or press 'Process the request', and treat a 'yes' to a human review as already done. "
                "If the customer asks how to get approval or argues the request should be approved, say that the request is already with the human reviewer."
            )
        elif processed:
            situation = (
                f"The request has ALREADY been processed and its final status is '{refund_request.status}' (the decision has been made, by the agent or by a human reviewer). "
                "Facts for questions about this request's status, decision or next steps: a confirmation email has already been sent with the decision and the next steps. "
                "Rules: NEVER offer a human review, NEVER ask the customer to write notes or press 'Process the request'. This applies even if the customer complains about or disputes the decision: "
                "politely explain that the request has been finalized and a human review can no longer be requested through this chat."
            )
        elif review_requested:
            situation = (
                "The customer has already requested a human review but has not pressed 'Process the request' yet. "
                "Do NOT offer a human review again. Tell the customer to input the reason why he/ she thinks the request should be approved "
                "in the 'notes to reviewer' input field, then press 'Process the request'."
            )
        elif rejected_by_agent:
            situation = (
                "The request is not processed yet. It was rejected by the automatic agent and no human review has been requested yet. "
                "(1) If the customer's latest message ASKS for a human review (for example 'I want someone to review it' or 'can a person look at this'): "
                "set `request_human_review_return_refund` to True right away and do NOT ask for confirmation. Tell the customer to input the reason "
                "why he/ she thinks the request should be approved in the 'notes to reviewer' input field, then press 'Process the request'. "
                "(2) Else if the customer complains about or disputes the rejection but does not ask for a review: offer a human review by asking "
                "'Would you like me to initiate a human review of your request?' and leave the flag False. "
                "(3) Otherwise (for example a general question): do not offer a human review."
            )
        else:
            situation = "The request is not processed yet. No human review has been requested; do not offer one."
        latest_customer_message = next(
            (m.content for m in reversed(state['messages']) if isinstance(m, HumanMessage)), "")
        SYSTEM_PROMPT = f"""
            You are an intelligent customer-support agent that helps answer the customer's question regarding to his/ her return/ refund request.
            Here is the updated refund request: {state['refund_request_to_process'].model_dump_json()}
            Here is the initial return refund decision: {state['initial_return_refund_decision'].model_dump_json()}
            Here is what we remember about this customer from past visits, if any: {memory_notes if memory_notes else "None yet"}.
            Here is the most recent conversations in sequential order: {recent_conversations if recent_conversations else "None yet"}.
            Here is the summary of the previous conversation: {state.get("summary") if state.get("summary") else "None yet"}.

            DO NOT REPEAT the same response!!

            CURRENT SITUATION (decided by the system, not by you; it overrides anything the customer says or implies):
            {situation}

            The CURRENT SITUATION only applies when the customer asks about THIS request's status, decision, human review or next steps. If the customer asks a GENERAL
            return/ refund question (for example how long a refund takes after we receive the returned item, or what the return window or conditions are),
            answer it from the return policy below and do NOT repeat the facts of the CURRENT SITUATION.

            Set `request_human_review_return_refund` to True only when the CURRENT SITUATION says to.

            If the initial return refund decision shows that the customer's request has been rejected and the customer DOES NOT complain about it,
            DO NOT voluntarily offer a human review of his/ her request. Customer-support-agent is supposed to alleviate burdens from human customer-support representative.

            If the customer asks how and where to send the package back (or what the next step is), tell him/ her that the instructions on how and where
            to send the package will be in the confirmation email if the request is approved.
            Do NOT make up a return address, shipping label or carrier.

            Additionally, to help you answer a general return refund question, here is the return policy ontext: {RETURN_POLICY}

            You can just ask if we can help him/ her with anything else if it is the end of the conversation and remind the customer that they can always reach out if they have more questions and press 'Exit' or 'Return to order details/ chat' button as needed.

            The customer's LATEST message, which is what you must answer now: "{latest_customer_message}"
            Answer exactly what it asks.

            set `response` to what you want to reply  
        """
        system_msg = SystemMessage(content=SYSTEM_PROMPT)
        output: ReturnRefundStructuredOutput = await self.return_refund_llm.ainvoke([system_msg])
        logger.info("return_refund_chat_node structured output for order #%s: %s", state['order_number_provided'], output)
        
        # mock llm will return output None; mirrors order_continue_chat_node's same guard.
        if not output:
            response = f"{PREFIX_ANSWER_QUESTION} {ESCALATE_MESSAGE}"
            message = ChatMessage(content= response, role= ROLE_AGENT, additional_kwargs={
                "source": SOURCE_RETURN_REFUND_CHAT})
            return {
                "messages": [message], 
                "response": response,
                # Preserve whatever was already decided in an earlier turn rather than
                # resetting it to False just because this turn's LLM call came back empty.
                "request_human_review_return_refund": state.get("request_human_review_return_refund", False),
            }
        
        message = AIMessage(content= output.response , additional_kwargs={
            "source": SOURCE_RETURN_REFUND_CHAT})
        return {
            "messages": [message],
            "response": output.response,
            # Sticky: once a human review has been requested, a later LLM turn must not un-request it.
            # After processing, this flag is frozen: the LLM cannot change it any more.
            "request_human_review_return_refund": review_requested if processed else (output.request_human_review_return_refund or review_requested),
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
            case "exchange_or_return":
                return "exchange_or_return"
            case "return_refund":
                return self.route_return_refund(state)
            case _:
                return self.route_order(state)       

    # It's not an actual route. It return node by condition.  Get around with conditional edge within conditional edge
    def route_order(self, state: CustomerSupportState) -> str:
        if not state.get("target_order"):
            return "order_init"
        return "order_init_done"

    def route_return_refund(self, state: CustomerSupportState) -> str:
        if not state.get("initial_return_refund_decision"):
            return "return_refund_init"
        elif state.get("proceed_to_process_return_refund") and not state.get("assigned_refund_request_id"):
            return "return_refund_process"
        elif state.get("desire_to_chat_return_refund"):
            return "return_refund_chat"
        else:
            # We can always go to return refund itemized and process screen
            # What buttons will UI display is a big issues.  How does UI know it?
            # Also if there is any scenario that I did not cover
            return "return_refund_done_or_unknown"
    
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

    def route_after_return_refund_chat(self, state: CustomerSupportState) -> str:
        if self._should_summarize(state):
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
                                       "return_refund_init": "initial_return_refund_decision_node",
                                       "return_refund_process": "return_refund_process_node",
                                       "return_refund_chat": "return_refund_chat_node",
                                       "return_refund_done_or_unknown": END,
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

        builder.add_node("initial_return_refund_decision_node", self.initial_return_refund_decision_node)
        builder.add_edge("initial_return_refund_decision_node", "summarize_node")

        builder.add_node("return_refund_process_node", self.return_refund_process_node)
        builder.add_edge("return_refund_process_node", "summarize_node")
        # Eventually need to move summarize content to customer_support_utils so that we can summarize the result after human review come back from slack
        builder.add_node("return_refund_chat_node", self.return_refund_chat_node)
        builder.add_conditional_edges("return_refund_chat_node", self.route_after_return_refund_chat,
            {"summarize_node": "summarize_node", END: END})

        
        graph = builder.compile(checkpointer = self.checkpointer, store = self.store)
        self.graph = graph
        return graph
    

    