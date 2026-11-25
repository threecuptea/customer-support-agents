## Human-in-the-loop

### How human-in-the-loop work in LangGraph's interrupt - Command resume framework

When human-in-the-loop step is needed, issue `interrupt` with key-value dictionary of info to convey to the frontend like actions (action buttons), and message. LangGraph captures state in StateSnapshot including all accumulated messages (HumanMessage, AIMessage and ToolMessage).  and checkpoint_id. In LangGraph, you can invoke a config with thread_id and checkpoint_id, it will execute/ resume the worklfow of that thread at that checkpoint_id. That's how you can test partial workflow in LangGraph. `interrupt` will put the thread at `interrupted` state.  When a human press a button, API will issue a Command(resume=resume_value). Langugraph will resume the workflow at the beginning of the `interrupt` node. That's where checkpoint points to.  The resume_value will feed the return of the `interrupt` function.  That's how we can resume lines following `interrupt` function. It's important that `interrupt` need to be at the very beginning of that node.  Any preparation should be in a separate node.

**We implememented Langgraph interrupt - Command resume framework in Approval workflow used by CSR to draft an email by LLM.** The CSR can choose `approve/ edit/ reject`. Edit will do a minor modification on the content.  Reject will give the feedback and ask for re-draft. It is blocking the thread until the requester press any of those buttons.

### We will implement human-in-the-loop in the manual approve/ reject/ flag return/ refund business workflow. However, we won't use LangGraph's interrupt - Command/ resume fraemwork.

The customer will receive a confirmation email instead.  It's asynchronous and non-blocking in terms of system design.  It's blocking from the business perspective.  A return/ refund request won't move forward until a CSR review it.

**Why do I decide not to use Langgraph interrupt - Command resume in return/ refund processing?**
Once a thread is in `interrupted` state, we need to invoke with Command/ resume in order for the graph to operate normally.  If the app accidentally invoke the graph without Command/ resume, Langraph will issue a fresh `interrupt`. Yes, it will `re-interrupt`.  Customer-support-agent is an interactive app with multiple endpoints.  The customer might like to chat with AI agent after processing the refund request. We shouldn't block the customer from using the app after the interrupt. Then, we have to check if the thread is in `interrupted` state and invoke with Command/ resume for all endoints if it is.  Doing so will unblock the graph and defeat the purpose of `interrupted` which is blocking!!

Langgraph interrupt - Command resume framework work well if the person to request LLM's action is also the person to review it like CSR asking LLM tp draft an email.  That works just like chatting. However, Langgraph interrupt - Command will affect the customer/user interaction in the manual approve/ reject/ flag return/ refund business worflow and does not serves its goal.  That's my concern.

## Integrate with Slack Interactivity

### HTTP or WebSocket

There are two ways to integrate with Slack: **WebSocket** and **HTTP**. Before using WebSocket, please do some research if interactivity works in Socket Mode.  In Socket Mode screen, `Interactivity and Shortcut` choice will be disabled if Socket Mode is enabled.  However, I DID see Slack interactivity work in Socket Mode [Slack interactivity in Socket Mode example](https://github.com/threecuptea/slack-n8n-integration-hub).  I elaborate their advantages and disadvantage as the followings:

- Socket Mode is using `ws` or `wss` portocol. Data transports in plain text in `ws`.  On the other side, Slack HTTP is using Form URL encoding.  `wss` definitively is needed in the production to transport data in a secure manner.
- It is easy to scale out HTTP servers in the production. A load balancer can sit in the front of HTTP servers. Scale out `ws` or `wss` is not straight forward.
- Web socket maintain a persistent two-way connection. It's very convenient to integrate with Slack in Socket Mode in dev environment.
- To integrate with Slack in HTTP in dev environment, I have to expose my local URL to the public using `ngrok`.
  **IMPORTANT:** Configure the public webhook full path as the request URL in the `Interactivity & Shortcut` screen.
- n8n out-of-box only support integrating with Slack interactivity. That's why I am more comfortable with integration with Slack in HTTP.

### Prevent from 'double click' and 'double update' for concurrency

- to prevent `double update`, we will only update the request if its status is at `wait_for_manual_review`
- to prevent `double click`, we will send Slack interactivity replacement w/o any button and `reason` input box plus acknowledge text. [Slack interactive replacement plus acknowledge](/images/screenshot_post_interactive_text.png) so that a CSR can tell a refund request being reviewed by his/ her colleague from the one not yet reviewed.

## To be or not to be: main:app and slack_webhook:app as separate apps or slack_webhook as an APIRouter to main:app

I made a decision to have slack_webhook as a separate FastAPI app (endpoint `/webhook/slack/interactive`) and start it at a different port for the following reason:

- They serve very different purposes. main:app provides all customer-support-agents APIs and slack_webhook only provides a webhook to the slack app.
- I want slack_webhook isolated.  I don't want customer-support-agents APIs being affected if slack_webhook went down for some reasons
- slack_webhook in dev is exposed as a public URL and I like the security risk as limited as possible

## Store refund requests in Redis or persistent stores like Postgres

The decision that I set up slack_webhook as a separate FastAPI app has an unexpected impact. main:app and slack_webhook:app live in separate memory spaces.  `slack_webhook.py` won't be able to see any refund request that `main.py` store in memory.  I have to resort to an external persistent store or a cache to communicate between main:app and slack_webhook:app.  I chose Redis over persistent stores like Postgres:

- I will simply serialize Pydantic RefundRequest BaseModel into Redis cache as a value and deserialized it back to parse and or modify it.  I am NOT using sophisticated RDBM modeling or referential intetrity.
- I am using demo data to dynamically adjust orders to meet refund request criteria. I also need to periodically clean up refund requests as a temporary storage for demo purpose. It is pretty easy to use redis-cli to retrieve the data to verify or clean up data.
- Redis is well adopted in industries.  I found that it is very easy to implement retrieve, insert, update, update with optimistic locking plus seconday index.

## Conversation summaries run in the background

`summarize_node` compresses a thread's messages into `summary` and long-term memory. Request flows never wait for it: they end at `mark_summarize_due_node`, and the service runs the summary on the same thread in a background `asyncio` task after the response is returned. A per-thread `asyncio.Lock` makes the next request (or Exit) on that thread wait for an unfinished summary, so two runs never write one thread's checkpoint at the same time. Exit summarizes too, and skips the LLM when nothing is new. Details, rejected options and measurements: [CSA-30](impl/CSA-30-background-summary.md)
