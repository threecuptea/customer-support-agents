# CSA-30 post-adjustment (after PR #28/#29)

## Source code: Adjust the followings so that it's easy to tell their LangFuse tracing apart.
  - The run_name `summarize_on_exit` : if invoke from  `summarize_on_exit` 
  - The run_name `summarize_due` : if invoke from  `summarize_due`
## Tests
  -  `test_response_returns_before_the_background_summary` in tests/test_background_summary.py should be able to use _FakeSummarizeLLM without a gate since the following source codes have ensured the the response will return before summarize task get scheduled.
  ```python
    state = await _locked_ainvoke(request.app, graph_input, config, run_name=run_name, tags=tags,
                                  invoke_from=invoke_from, user_id=user_id)
    if state.get("summarize_due") and invoke_from not in SUMMARIZE_INVOKES:
        # app and user_id, not request: the task outlives the request.
        request.app.state.summaries.schedule(_background_summarize(request.app, config, user_id))
  ```
  
