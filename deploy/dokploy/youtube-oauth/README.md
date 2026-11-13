# Proactive YouTube OAuth health

Install monitor.py, check.cjs, and a private config.json under /opt/postiz-amssoft/automation/youtube-oauth. Run the supplied timer every 15 minutes. Runtime state stays in /var/lib/amssoft-youtube-oauth; do not commit that state or production configuration.

The checker uses OAuth credentials already present in the Postiz container. Access tokens with at most 20 minutes remaining are refreshed, then verified against the existing YouTube channel before an atomic conditional update. Retain the original refresh token when Google does not return a replacement. Never overwrite concurrently updated native credentials. Transient errors are retried on a later run; permanent refusals are cached until authorization/configuration changes and mark the channel for owner action. No publishing or deletion occurs.

An invalid_grant response is not proof of Testing mode. The project owner must inspect Google Auth Platform publishing status and policies. External Testing grants with YouTube scopes expire in seven days; production removes that testing limit but does not prevent revocation or other Google expiration conditions. Existing revoked grants require fresh consent. Do not clear refreshNeeded merely to make the channel look healthy.

After correcting the Google project and reconnecting the existing channel, run monitor.py --force-refresh once and verify ready, renewed, and matchingChannel. Do not repeatedly force revoked grants. Exit code one means unhealthy/owner action; the timer remains active. The local JSON status is not an email or external alert delivery service.

Run test-check.cjs in a Node environment without production credentials. Tests mock OAuth and channel responses: current access, proactive renewal, refresh-token preservation, revoked-grant suppression, transient errors, account identity and concurrent changes. No production Google identifiers or tokens belong in this repository.

Official references: https://developers.google.com/identity/protocols/oauth2#expiration and https://developers.google.com/youtube/v3/guides/authentication .
