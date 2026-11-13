# Native Postiz WhatsApp Status recurrence

Postiz is the only publication calendar. This host automation discovers videos and creates native Postiz posts with a daily interval. The WhatsApp bridge has no schedule, recurrence configuration, source-folder mount or manual publisher. It receives an immediate send request only when the Postiz workflow is due.

Install recurrence.py as /opt/amssoft-postiz-status-automation/recurrence.py and create a private config.json there from the example. Existing production config/state must be migrated, not replaced by the example. State is /var/lib/amssoft-postiz-status/recurrence.sqlite. Preserve managed post IDs to avoid duplicate series. Install the two systemd units and disable/remove legacy bridge agenda units before enabling the new timer.

The configuration file is private runtime data and must never be committed. No API key is embedded in this code/config; the existing organization key is read privately through the local Postiz database. Keep directory ownership, protection and resource limits from the deployment audit in mind. Changing daily configuration belongs here or in the native Postiz calendar, never in the WhatsApp operator panel. Current timing settings must be preserved during deployment.
