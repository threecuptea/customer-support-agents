## Customer-Support-Agents

Customer-support agents that combine LangGraph workflow automation with human-in-the-loop review. They answer general FAQs, handle order inquiries, and automate return/ refund requests, escalating to a human when a request is outside the agent's authority.

### Customer-support workflow

The diagram below is the compiled LangGraph for the customer-support flow. Each API call (`/api/support/...`) enters at `__start__` and a router sends it to one branch. Dotted arrows are conditional edges, and their labels are the router's decisions.

- **General FAQ**: `general_faq_eval_node` -> fuzzy match -> LLM match, escalating when no match is confident enough.
- **Order inquiry**: `retrieve_target_order_node` -> `detect_order_revisit_node` -> a static first reply for a new inquiry, or `order_continue_chat_node` for a revisit and for every later turn.
- **Exchange/ return and refund**: `exchange_return_reason_recommendation_node` -> `initial_return_refund_decision_node` -> `return_refund_process_node`, with `return_refund_chat_node` for questions along the way.
- `summarize_node` condenses finished conversations into long-term memory before the run ends.

The diagram is generated: run `backend/workflow/draw_workflow_images.ipynb` and paste the output of `draw_mermaid()` here.

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	summarize_node(summarize_node)
	general_faq_eval_node(general_faq_eval_node)
	general_faq_fuzz_match_node(general_faq_fuzz_match_node)
	general_faq_llm_match_node(general_faq_llm_match_node)
	order_continue_chat_node(order_continue_chat_node)
	retrieve_target_order_node(retrieve_target_order_node)
	detect_order_revisit_node(detect_order_revisit_node)
	order_init_static_response_node(order_init_static_response_node)
	exchange_return_reason_recommendation_node(exchange_return_reason_recommendation_node)
	initial_return_refund_decision_node(initial_return_refund_decision_node)
	return_refund_process_node(return_refund_process_node)
	return_refund_chat_node(return_refund_chat_node)
	__end__([<p>__end__</p>]):::last
	__start__ -. &nbsp;return_refund_done_or_unknown&nbsp; .-> __end__;
	__start__ -. &nbsp;exchange_or_return&nbsp; .-> exchange_return_reason_recommendation_node;
	__start__ -. &nbsp;general_faq&nbsp; .-> general_faq_eval_node;
	__start__ -. &nbsp;return_refund_init&nbsp; .-> initial_return_refund_decision_node;
	__start__ -. &nbsp;order_init_done&nbsp; .-> order_continue_chat_node;
	__start__ -. &nbsp;order_init&nbsp; .-> retrieve_target_order_node;
	__start__ -. &nbsp;return_refund_chat&nbsp; .-> return_refund_chat_node;
	__start__ -. &nbsp;return_refund_process&nbsp; .-> return_refund_process_node;
	__start__ -.-> summarize_node;
	detect_order_revisit_node -.-> order_continue_chat_node;
	detect_order_revisit_node -.-> order_init_static_response_node;
	exchange_return_reason_recommendation_node --> summarize_node;
	general_faq_eval_node -.-> general_faq_fuzz_match_node;
	general_faq_eval_node -.-> general_faq_llm_match_node;
	general_faq_eval_node -.-> summarize_node;
	general_faq_fuzz_match_node -.-> general_faq_llm_match_node;
	general_faq_fuzz_match_node -.-> summarize_node;
	general_faq_llm_match_node --> summarize_node;
	initial_return_refund_decision_node --> summarize_node;
	order_continue_chat_node -.-> __end__;
	order_continue_chat_node -.-> summarize_node;
	order_init_static_response_node --> summarize_node;
	retrieve_target_order_node -.-> detect_order_revisit_node;
	retrieve_target_order_node -.-> summarize_node;
	return_refund_chat_node -.-> __end__;
	return_refund_chat_node -.-> summarize_node;
	return_refund_process_node --> summarize_node;
	summarize_node --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

### Approval workflow (CSR draft letters)

A customer-support representative (CSR) asks the AI to draft a customized customer letter, and a human approves it before it is "sent". This is the LangGraph `interrupt` / `Command(resume=...)` pattern: `human_review` pauses the thread execution until the CSR responds.

- `drafter` writes the draft with the LLM (using the CSR's feedback on a redraft).
- `human_review` interrupts with the draft and three actions: **approve** (send as is), **edit** (send the CSR's own revised text), or **reject** with feedback.
- On reject, the graph loops back to `drafter` for a redraft, up to 3 revisions; after that it finalizes with the feedback unresolved.
- `finalize` records the final letter and the status (`sent` or `sent_with_unresolved_feedback`).

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	drafter(drafter)
	human_review(human_review)
	finalize(finalize)
	__end__([<p>__end__</p>]):::last
	__start__ --> drafter;
	drafter --> human_review;
	human_review -.-> drafter;
	human_review -.-> finalize;
	finalize --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc
```

### Customer-Support-Agents Business Features

- The `customer-support-agents` app is a multi-tenant app by role. Users will be assigned to `customer` page if their role is `customer` and `csr` page if their role is `csr`.  Customers can ask general FAQ, order-specific inquiry and request a return/ refund and processed by automatic AI agents or reviewed by a customer-support representative.  CSR can get AI agent to draft customer-support emails and review them before sending out. 
- Most customer-support app requires the customer to provide an order number even though recent order info is available. Unnecessary stress might incur if customers do not have receipts at hands.  We will pre-fill the  `CustomerContext` for a login customer. `CustomerContext` will have recent order(s) in details.  We will present an order summary for an order inquiry or present an itemized order for a return/ refund request. The customer can simply click radio button(s) to start his/ her inquiry/ request.
- People don't like customer-support agents because it does not sound intelligent or real and it keeps repeat the same answers again and again.  The `CustomerContext` equipped with the customer's title(salutation) and background information helps customer-support agents look professional and able to strike meaninful conversations: chat based upon order status (for example, look for tracking number link to track order status when the order is in `transit` status). Also with the help of long-terms memory and short-term snapshot state management provided by LangGraph framework, our customer-support agents not only remember conversations of this session but also know the customer's prior visits. That makes out agent look human-like and cool.
- I spent a lot of time on researching FAQs, return policy, exchange/ return recommmendation, what orders should be approved/ rejected by automatic agents and what orders requires human reviews, how to handle human review requests, what situations should be covered in order inquiry chat and how to craft the prompt accordingly and what situations should be covered in return for refund chat and craft the prompt accordingly. I put a lot of efforts into it from ideation to implementation. The system looks fine and ready to plug in a real inventory system to a certain extent. 
- What are add-on values of a `customer-support-agents` app? Here is my take.
  - It alleviates customer-support representatives from manually answering lots of order inquiries or manually approving/ rejects overwhelming return/ refund requests. AI agents can answer order inquiries or auto approve/ reject return/ refund requests within their authority given clear instructions and leave cases requiring human judgements to CSRs.
  - It provides a feedback loop to improve CSA.  For example, if there are still a lot of cases being escalated to CSRs, can we loosen up auto-approve / auto-reject criteria so that some workloads can be moved to auto-agent bucket?  Feedback loop is essential to the success of a customer-support app. 
- I design return/ refund auto aprove/ reject and human review (human-in-the-loop) based upon the following 5 principles:
  - An AI agent will auto appove a request that have its order amount within its authorized amount and it is requested within the return window defined in the company's return policy.
  - An AI agent will auto reject a request if it is requested passing the return window deadline.
  - An AI agent will auto reject a request if the request include a non-refundable item defined in the company return policy.
  - A request exceeding an AI agent's authorized amount will automatically be escalated to a human review.
  - A auto-reject request will get one chance of a huamn review upon the customer's request. The customer either explicitly request a human review or complain about the auto-reject decision and the chat agent escalate it after confirming with the customer's intent.
- I add exchange/ return for refund survey to give a sound recommendation as well as collect information for feedback. Elaborate:
  - **Changed Mind or Impulsive Buy:** does Flash sales, and aggressive discounting contribute to it? or is there a new low-priced competitor that we should watch for?
  - **Doesn't Match Description or Photos:** improve product photograph, review product quality and update descriptions.
  - **Damaged or Defective:** we not only file claims for defective items but also re-evaluate whether to continue carrying those products if detectives occur a lot at the manufacturer level.
  - **Wrong Item Shipped:** It is definitively a warning sign of warehouse operations.

For requests of items damaged or defective or wrong items shipped, we also escalate them to a customer-support representative so that a CSR might ask the customer to show photos of proofs and make human judgments based upon photos and other factors. A CSR can also approve to pay for the return shipment and expedit the replacement too.

### AI System Design & Philosophy
I built [Agentic RAG](https://github.com/threecuptea/agentic_ai/tree/master/sonya_agentic_rag_v2) on Feb. 2026 and every RAG query will only invoke LangGraph workflow once.  Once the LangGraph's agentic workflow is invoked, it is in a close loop with nodes and conditional edges until it finishes and generates outputs. It is very straight-forward.  No FastAPI is involved. Python Gradio UI invokes LangGraph's agentic workflow directly and stream the output back.

I built [Prelegal](https://github.com/threecuptea/prelegal) on May. 2026. I did not use LangGraph.  **I use FastAPI combined with OpenAI Agent SDK in an Agent Loop architect**. The agent is given required fields defined for each legal template and instructed to guide a user to provide one or two fields in each conversation. UI invokes OpenAI Agent SDK multiple times via FastAPI in a session.  However, the agent is in a close-purposed loop - collecting inputs of all required fields.

`Customer-support-agents` is much more complicate as shown in the worflow diagram.  It covers general FAQs, order inquiries, exchange or return recommendations, returns for refunds. Order inquiry topics can be from an 'pending' order, tracking an order in 'transit', find the whereabouts of a shipment to listen to the customer's complaint about items received and more. The customer can chat multiple-runs with LLM or even on multiple orders.  For returns for refunds, more conditional principles mean more branches/ routes to cover.  Returns for refunds requirs multiple steps: validate return product(s) and quantities, calcualate amount to be refund and convey the initial decision and ask if proceeding to process and chat along the way. `Customer-support-agents` is a multi-step, multi-run (invocation) AI system in overall.

Agent loop to the whole app is out of question because of the complexity of `customer-support-agents` app. What about applying Agent Loop to components like order inquiry or automate return/ refund?  Should I use LLM as a controller and assist it with tools calling or should I use function calls and only use LLM when we need reasoning/judgement based upon the context or engage smooth conversations with the customer?   

By now, a lot of AI engineers have consensus: LLM is **indeterministic**.  It's better to use a function to output based upon the amount refund due before tax > $500 or use that amount in a LangGraph's conditional routing (both are deterministic) rather than embedding $500 in the prompt and ask LLM to make decision base upon it, which is indeterministic in nature.  There are two misconception. One is that tool-calling does not cost tokens. Wrong. Tool calling depends upon LLM to decide what tool to use and craft arguments for tool calls. It definitively consume tokens.  Another misconception is that LLM automatically call the tool for you.  Wrong. LLM only recommend what tool to use and what arguments to pass. AI engineers still needs to add a node to retrieve `tool_calls` and the associated `arguments` and make a call and handle the result.

I built `customer-support-agent` based upon the principle: use `deterministic` codes/ functions whenever possible. I use the function `get_initial_return_refund_decision` in `initial_return_refund_decision_node`. `get_initial_return_refund_decision` includes 4 sub functions from validation, populate refund request, calculate refund amount including tax to generate an initial decision. The node `initial_return_refund_decision_node` is `deterministic`.  One AI engineer complained in Medium Digest that his LLM approve a refund request that it should not approve. That would never happen here. `return_refund_process_node` is triggered by the customer clicking `Process the request` button. The process flow is using codes.  `return_refund_process_node` is deterministic. I and Claude even make our best effort to make  `return_refund_chat_node` `deterministic`.  I will eleborate in the following section. 

### Chat prompt tuning and LLM test Harness
I draft prompts for `order_continue_chat_node` and `refund_request_chat_node`.  I spent a lot of time fine tuning them and I still see inconsistent result. For example, in `order_continue_chat_node`, I explicitly instruct LLM to 'ask the customer whether he/ she would like to cancal the order and needs our help but DO NOT escalete it if a revisiting customer of an order with long `pending` status just started the conversation.  However, LLM still set `order_issue_escalated` prematurely. In `refund_request_chat_node`, LLM sometimes sets `request_human_review_return_refund` when it asked the customer 'Would you like me to initiate a human review of your request?'.  It is very frustrating!!

One of problems is that situations in chat nodes often involve multiple variables.  Some are from state CustomerSupportState, some are from RefundRequest.  There are multiple statuses too. When the prompt says "If the initial_return_refund_decision shows that the customer's request has been rejected by an automatic agent", LLM does not know what variables to look for that situation. Claude rewrote it as the following code 
```python
	refund_request = state["refund_request_to_process"]
	decision = state["initial_return_refund_decision"]
	processed = (state.get("assigned_refund_request_id") or 0) > 0
    review_requested = bool(state.get("request_human_review_return_refund"))
    rejected_by_agent = decision.order_refund_status in (
        OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_DAYS, OrderRefundStatus.ORDER_NON_REFUNDABLE_DUE_TO_ITEMS)
    if processed and refund_request.status == "wait_for_manual_review":
        situation = (
			:
		)	
    elif processed:
        situation = (
			:
		)	
    elif review_requested:
        situation = (
			:
    elif rejected_by_agent:
        situation = "The request is not processed yet. It was rejected by the automatic agent and the customer has NOT requested a human review yet, so a human review may be offered only if the customer complains about the rejection."
    else:
        situation = "The request is not processed yet. No human review has been requested; do not offer one."
	STEM_PROMPT = f"""
            :
			:
            CURRENT SITUATION (decided by the system, not by you; it overrides anything the customer says or implies):
            {situation}	         
```
I calls it `deterministic-situation-priority-flow` pattern. Let us spell out what the situation exactly is rather than let LLM guess what situation is. It enlist situations in order of priority.  The most strict situation is at the top. 

`order_continue_chat_node` even go futher. I calls it `deterministic-prompt-text-rendered-by-situation` pattern. Contrast to monolithic rule approach, it renders prompt text by situation plus always on prompt text (See `workflow/situation_order.py` for the implementation details) There are two unbeatable strengths:
  - It isolates prompt generation by the determinstic situation. That eliminates a chance having contradictory rules competing with each other in a monolithic rule approach
  - It can leave an audit trail: what a situation was selected in each call. 

Claude also contribute LLM test harness in `CSA-18: Real-LLM evaluation harness for chat nodes`  Motivation: the mock LLM returns `None` for `with_structured_output`, so `return_refund_chat_node`/`order_continue_chat_node` could only be tested on their escalate fallback in unit tests. We like to quickly test LLM models on multiple cases in multiple trials and score them. Score must pass the threshold.  If not, we fine tune prompts for those chat nodes until they are solid enough to pass the threshold.  

Claude provides a customized graceful solution (See `tests/llm_harness` files for the details).  That can be applied to any LangGraph nodes which are all  `Callable[[dict], Awaitable[dict]]`, an async await function call taking a `dict` input and output a `dict`.  Then we inject the input state `dict` via the `build_state` parameter of `Case` class.  The following code snippet demonstrates how `customer-support-agents` LLM test harness piece together: 
```python
	Node = Callable[[dict], Awaitable[dict]]
	@dataclass
	class Case:
		id: str
		description: str
		build_state: Callable[[], dict]          # fresh state per trial (nodes must not share mutable state)
		must_contain: list[Phrase] = field(default_factory=list)
		must_not_contain: list[str] = field(default_factory=list)
		# Expected values of fields in the node's returned dict. A missing key counts as False,
		# because nodes only return e.g. `order_issue_escalated` when they set it.
		expect: dict[str, Any] = field(default_factory=dict)
		threshold: float = 0.8                    # required pass rate over `trials`
		known_issue: str | None = None            # below threshold is reported, not failed

    async def run_case(node: Node, case: Case, trials: int = 5, concurrency: int | None = None,
                   retries: int = 3, backoff: float = 1.0) -> CaseResult:
    """Call `node` `trials` times and score each answer.
    """
    if concurrency is None:
        import os
        concurrency = int(os.getenv("LLM_CONCURRENCY", "4"))
    if case.known_issue:
        trials = 20
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one() -> dict:
        async with gate:
            for attempt in range(retries + 1):
                try:
                    return await node(case.build_state())
                except Exception as exc:  # noqa: BLE001 - classified below
                    if is_transient(exc) and attempt < retries:
                        await asyncio.sleep(backoff * (2 ** attempt))
                        continue
                    raise

    outputs = await asyncio.gather(*(one() for _ in range(trials)), return_exceptions=True)


	def _evaluate(node, case):
		result = asyncio.run(run_case(node, case, TRIALS))

	@pytest.mark.parametrize("case", RETURN_REFUND_CASES, ids=lambda c: c.id)
	def test_return_refund_chat_node(agent, case):
		_evaluate(agent.return_refund_chat_node, case)

	@pytest.mark.parametrize("case", ORDER_CONTINUE_CASES, ids=lambda c: c.id)
	def test_order_continue_chat_node(agent, case):
		_evaluate(agent.order_continue_chat_node, case)

	@pytest.mark.parametrize("case", REVISIT_CASES, ids=lambda c: c.id)
	def test_detect_order_revisit_node(agent, case):
		_evaluate(agent.detect_order_revisit_node, case)
```
Here is one Case example for Request and Refund
```python 
	_rr("RR-8", "rejected, not processed, customer complains: offer review but do NOT set the flag yet",
        request_status="pending", assigned_id=0, flag=False,
        question="This is unfair, I only pass deadline 1 day, I should get approved",
        must_contain=["human review"], expect={"request_human_review_return_refund": False}),
```    
`must_contain` define what the response must contain one of them. `must_not_contain` define what the response must not contain one of them and `expect` specifies what property value should be in the `state` of `CustomerSupportState`.  
Claude also get LLM_MODEL and LLM_TEMPERATURE commmand line override working. Therefore, I can run
```bash
LLM_MODEL=gpt-4o-mini RUN_LLM_TESTS=1 LLM_TRIALS=20 uv run pytest -m llm -s
```
to run 20 trials on each cases. (default temperature 0; LLM_TRIALS=20 for fewer flukes)
The result after Claude fine tuned prompts of `return_refund_chat_node`/`order_continue_chat_node`/`detect_order_revisit_node` is very amazing. In a full harness on `gpt-4o-mini`, all 31 cases pass 20/20 in multiple runs. Harness on `gpt-4.1` passed 20/20 in multiple runsearlier.

The following is a table view demonstrating `deterministic-situation-priority-flow` of `return_refund_chat_node` and cases it covers:

| # | Condition | Situation | Flag rule | Harness cases |
|---|---|---|---|---|
| 1 | `processed` and `refund_request.status == "wait_for_manual_review"` | already with a human reviewer (15-30 min email); never offer/ask a review, never ask for notes or 'Process the request'; a 'yes' to a review is already done | frozen | RR-1, RR-2, RR-3, RR-4, RR-10, RR-11 |
| 2 | `processed` (any other status: `auto_approve`, `auto_reject`, `manual_*`) | finalized, confirmation email sent; never offer a review even if the customer disputes (explain it can no longer be requested in chat) | frozen | RR-5, RR-6 |
| 3 | `review_requested` (not processed) | do not offer again; tell the customer to fill the 'notes to reviewer' box and press 'Process the request' | sticky | RR-7, RR-12 |
| 4 | `rejected_by_agent` (not processed, no review requested) | three branches inside the text: (1) latest message ASKS for a review -> set flag True now, no confirmation question, tell them to fill the notes box and press Process; (2) only complains/disputes -> offer 'Would you like me to initiate a human review of your request?', flag stays False; (3) otherwise -> no offer | set only by branch (1) | RR-8, RR-9, RR-13 |
| 5 | default (not processed, not rejected, no review requested) | no human review has been requested; do not offer one | False | none (gap) |


### Human-In-The-Loop
I use `human-in-the-loop` term in a broad perspective and it does not matter what mechanism or what architect it is implemented. `customer-support-agents` use `human-in-the-loop` in two places:

**CSR Approval workflow:** when a CSR requests a draft of a topic, LLM draft an email in the  `drafter` node, the workflow goes to `human_review` node and issue `interrupt` statement with the code snippet:
```python
async def human_review(state: ApprovalState) -> Dict[str, Any]:
    """Pause for the human to approve, edit, or reject the draft."""
    logger.info("Awaiting human review")
    response = interrupt(
        {
            "type": "approval",
            "task": state["task"],
            "draft": state["draft"],
            "revision_count": state.get("revision_count", 0),
            "actions": ["approve", "edit", "reject"],
            "message": (
                "Review the draft. **Approve** to send it, **Edit** to send your "
                "own revised version, or **Reject** with feedback to request changes."
            ),
        }
    )
```
LangGraph paused the thread execution and remember the `checkpoint_id` of the `human_review` node. It takes one of 
three actions: **approve** (send as is), **edit** (send the CSR's own revised text), or **reject** with feedback. When a CSR press one of action button with his/ her optional input, UI is calling the following code snippet
```python
async def approval_decide(data: ApprovalDecision, request: Request):
    """Resume the approval workflow with approve / edit / reject."""
    graph = request.app.state.approval_graph
    config = {"configurable": {"thread_id": data.thread_id}}

    action = data.action.lower()
    resume_value: dict = {"action": action}
    if action == "edit":
        resume_value["content"] = data.content or ""
    elif action == "reject":
        resume_value["feedback"] = data.feedback or ""  

    try:
        result = await graph.ainvoke(Command(resume=resume_value), config)
```
LangGraph re-invoke the thread at the `checkpoint_id` . The `resume_value` feeds the `response` of `interrupt` statement.  That's why it resume the flow of that thread. `reject` will direct the workflow back to the `drafter` node with the `feedback` property filled. Both `approve` and `edit` will move the workflow to `finalize` node then `END` node.

**It's important to know that LangGraph does not hold on the thread when we issue `interrupt`**.  There is no extra overhead.  The `interrupt` simply is built upon LangGraph's existing StateSnapshot management that we can use it to test executing workflow from any checkpoint_id on.  

**Customer human review workflow of a return/ refund request:** When a return/ refund request requires a human review, we will send the request detail in a Slack's interactivity block message to a Slack channel. A CSR will review the request in the channel and press one of buttons `Approve`/`Reject`/`Flag`. That will send a confirmation email to the customer. An interactivity block response with `action`, `decided_by`, `decided_date` and `decision_reason` will post back to the webhook hosted in `customer-support-agents` app and update the customer's `RefundRequest` record. It is `human-in-the-loop` because the customer's `RefundRequest` is blocked from moving forward until a CSR reviews his/ her request.  However, We did not issue an LangGraph `interrupt` to pause/ block the thread execution. `human-in-the-loop` is implemented in an asynchronous manner.

**Why do I decide not to use Langgraph interrupt - Command resume in return/ refund processing?**
Once a thread is in an `interrupted` state, we need to invoke with Command/ resume in order for the graph to unpause the thread execution.  If the app accidentally invoke the graph without Command/ resume, Langraph will re-execute the thread at the `checkpoint_id`.  Langugraph will issue a fresh `interrupt` because no resume action to feed the response of the `interrupt`. Each `interrupt` has its `id`. We have to match to unpause them one by one. It will get complicated. 

`Customer-support-agents` is an interactive app with multiple endpoints.  We shouldn't block the customer from using the app after requesting human review. Then, we have to check if the thread is in `interrupted` state for all endpoints and invoke with Command/ resume with an artificial action if the current thread is in `interrupted` state. Doing so will unblock the thread execution.  That will defeat the purpose of `interrupt` which is blocking!!

Langgraph interrupt - Command resume framework work well if the person to request a LLM's action is also the person to review it like CSR asking LLM to draft an email.  That works just like chatting natually. However, Langgraph interrupt - Command will affect customer's interaction with the support agent and does not serve the purpose.  That's my concern.

### Technical design

The entire project is packaged into a Docker container.

The backend is in `backend/` — a `uv` project (Python 3.12) using FastAPI.  I follow a consistent architect design across all my projects.  I separates API files into `routes` and `services` and `models`. I also added a `workflow` folder that all LangGraph workflows and supporting Python modules reside in. Currently, all API endpoints are either in `backend/main.py` or in python modules of `routes` subfolder.  `models/model.py` have all model schemas shared by `auth` and `customer_support` service and `customer_support` workflow.  

The frontend is in `frontend/` — Next.js 16, React 19, Tailwind 4. It will be statically exported (`next.config.ts` → `output: "export"`) to `frontend/out/`.

Officially, we are using one Docker container deployment with one entry point. In Dockerfile,  API build will copy static output `frontend/out/` from `frontend-build` to its build and mount it so that FastAPI can serve them at runtime at port `:8000`. A docker container can be started with `scripts/start-xxxx.sh` (`xxxx` is a placehold).  In dev, it's easier to deploy `backend` and `frontend` separately. Start backend `uv run uvicorn --timeout-keep-alive 75 main:app --reload` at the backend folder and start `npm run dev` at the frontend folder. Use `localhost:3000` Next.js port to proxy to`localhost:8000` FastAPI port.  

I decide to build `customer-support-agents` in DEMO_MODE because return refund involves the product return window. The data in database will be stale and not testable.  I dynamically adjust data in memory in DEMO mode so that they always be testable.
