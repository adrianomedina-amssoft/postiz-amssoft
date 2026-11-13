# Daily Reel campaign with batch cooldown

Install planner.py under the host automation tree with sibling common/workflow_cancel.py. Keep config.json private. The user-approved campaign selects only its approved Instagram/Facebook channels; no Stories or WhatsApp providers are accepted.

Each distinct content hash is one campaign item. Natural filename order seeds persistent positions; new files append. Each item creates one non-recurring native Postiz post per approved network at a shared daily instant. Instagram explicitly sends share_to_feed=false and disables trial Reels. Facebook uses the existing single-video provider; feed visibility was explicitly accepted for the Reel by the operator. Do not claim Facebook has the equivalent Instagram no-feed control.

Pick the next available local hour between 06:00 and 23:00, with a configured safety gap against actual native posts and their interval expansions, and reserve known future group hours. Prefer the first campaign hour on subsequent days, moving to another free hour when needed. One campaign item per local calendar day. Dates already planned are stable; newly created external schedules need an operator conflict review.

A whole-cycle cooldown starts only after every retained item has been published successfully on all selected networks. Wait at least 60 complete days from confirmation of the final item, then create the next cycle from active files. Never use inter=1 or repeat each individual video every 60 days. Failed, partial or ambiguous outcomes need review and block automatic cycle completion.

Persist upload metadata, creation intent, exact native post IDs, cycle state and retirement state. Reconcile ambiguous creation by integration/date/media rather than blindly reposting. Confirmed HTTP 429 is retried on a subsequent timer run. Removing sources cancels queued future posts and verifies their Temporal executions before retiring the item; started or imminent posts require review. Preserve this SQLite database during upgrades.

Initial media validation uses stable regular MP4 files, no symlinks, bounded reads, hashes and an isolated ffprobe container. Actual video metadata must remain consistent while reading. Public repository files contain no production channel IDs, tokens, media, session data, databases or configured secrets.

Dockerfile.amssoft-reels reuses a verified base and compiles only the changed Instagram modules, preserving the frontend and all unrelated publishing modules. The compile helper translates the existing application aliases to their runtime relative paths. Run test-runtime.cjs against the resulting image to validate the actual DTO and both service modules. This avoids rebuilding the whole application on a shared VM.
