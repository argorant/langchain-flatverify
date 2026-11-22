# langchain-flatverify

LangChain tools that let an agent check whether email addresses can receive mail, one at a time or as a whole list, with [Flatverify](https://flatverify.com).

Flatverify checks email addresses on a flat monthly plan. Every plan is unlimited; plans differ only in speed. New accounts get 100 free checks, no card.

## Install

```bash
pip install -U langchain-flatverify
```

Create an API key in the [Flatverify app](https://app.flatverify.com) under API keys and set it:

```bash
export FLATVERIFY_API_KEY="fv_..."
```

## Quick start

```python
from langchain_flatverify import FlatverifyVerifyEmailTool

tool = FlatverifyVerifyEmailTool()
tool.invoke({"email": "maya.chen@amazon.com"})
# {'email': 'maya.chen@amazon.com', 'status': 'valid', 'sub_status': 'accepted',
#  'reason': '...', 'disposable': False, 'role': False, 'free': False, 'catch_all': False}
```

Give all tools to an agent:

```python
from langchain.agents import create_agent
from langchain_flatverify import FlatverifyToolkit

agent = create_agent(
    model="openai:gpt-5-mini",
    tools=FlatverifyToolkit().get_tools(),
    system_prompt="Check every email address before you add it to a list.",
)
question = "Which of these can receive mail? j.ortiz@salesforce.com, info@shopify.com"
agent.invoke({"messages": [{"role": "user", "content": question}]})
```

## Tools

| Tool | Name the model sees | What it does |
| --- | --- | --- |
| `FlatverifyVerifyEmailTool` | `flatverify_verify_email` | Checks one address. Returns `status`, `sub_status`, `reason` and the `disposable`, `role`, `free`, `catch_all` flags. |
| `FlatverifyBulkVerifyTool` | `flatverify_bulk_verify` | Checks a list as one job, waits for it and returns counts plus one row per address. Returns the `job_id` if the job runs longer than `wait_timeout`. |
| `FlatverifyGetJobTool` | `flatverify_get_job` | Returns the status of a bulk job and, once it is done, its rows. |
| `FlatverifyToolkit` | | All three tools sharing one API key. |

`status` is `valid`, `invalid`, `risky` or `unknown`. `sub_status` gives the reason, for example `accepted`, `mailbox_not_found`, `catch_all`, `role_account` or `disposable`.

Settings:

```python
from langchain_flatverify import FlatverifyAPIWrapper, FlatverifyBulkVerifyTool

wrapper = FlatverifyAPIWrapper(flatverify_api_key="fv_...", timeout=30, max_retries=3)
bulk = FlatverifyBulkVerifyTool(api_wrapper=wrapper, wait_timeout=300, max_results=1000)
```

Rate limited (429) and busy (503) responses are retried after the `Retry-After` delay, up to `max_retries` times. Other errors are returned to the model as a short message. The API key is never logged or shown in a repr. All tools support async (`ainvoke`).

## Use cases

- **Give your research agent an email check.** When the agent finds or writes a prospect address, it calls `flatverify_verify_email` before it uses it.
- **Gate a lead list before it reaches your sending tool.** The agent sends an exported list from Clay or Apollo through `flatverify_bulk_verify` and passes on only the valid rows; risky rows go to review.
- **Stop fake signups.** Call the tool from your signup flow to flag disposable and dead addresses before the welcome mail.
- **Route catch-all and role addresses.** Use `sub_status` to send `catch_all` to a slower step, `role_account` (info@, sales@) to a company-level flow and `disposable` straight out.
- **Re-check your CRM on a schedule.** Every plan is unlimited, so a monthly full re-check costs the same as none.

## Links

- Flatverify: https://flatverify.com
- API docs: https://flatverify.com/docs
- Support: support@argorant.com

## License

MIT. Flatverify by Argorant.
