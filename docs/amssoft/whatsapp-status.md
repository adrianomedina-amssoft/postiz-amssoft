# WhatsApp Status

The whatsapp-status provider uses a dedicated Status operator. Configure WHATSAPP_STATUS_URL and WHATSAPP_STATUS_TOKEN_FILE privately on the backend and orchestrator runtime, never NEXT_PUBLIC variables. The operator must mount the Postiz uploads directory read-only. It accepts only local MP4 files, a fixed expected WhatsApp account and one publication at a time.

Publication uses persistent idempotent jobs keyed by the Postiz post id. The provider returns pending and polls the operator; only SENT or owner CONFIRMED results become completed. Unknown outcomes are not automatically resent. An account awaiting login cannot send and remains pending. No generic chat/group routes are added.

This is a separate provider, with MP4-only validation and a client composer component. Existing Meta/YouTube integrations are retained. The operator's human UI continues to require password and TOTP; automation uses its own private service token.
