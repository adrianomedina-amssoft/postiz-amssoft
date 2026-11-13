# Managed Instagram/Facebook Stories

Install scheduler.py under the host automation tree with the sibling common/workflow_cancel.py module. Keep config.json private, including compose_project, directory, timezone, start_hour, interval_minutes, enabled, and channels mapping provider identifiers to approved account IDs. Use America/Porto_Velho for the posting timezone. Do not commit production account IDs or credentials.

The scheduler retains discovered asset order, imports approved local MP4s, and maintains native Postiz Story posts. Retiring a source asset cancels its future queued posts and verifies the corresponding native workflows are closed before marking local jobs removed. Preserve the state database and inspect ambiguous outcomes before retrying. Run on a timer; Postiz executes dates and the monitor owns no independent publication loop.
