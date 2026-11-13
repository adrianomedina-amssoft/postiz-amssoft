# AMS SOFT operational instructions

- This repository is public. Never commit production credentials, configured phone numbers, session files, personal messages, databases, media, backups or private deployment files. Use runtime variables and secret-file mounts.
- User preference: batch changes before pushing and avoid simultaneous or redundant GitHub Actions builds. Keep at most one necessary application build for a code change. Deployment-only and documentation-only changes must not rebuild the application.
- Preserve branch/path filters and concurrency cancellation. Check the workflow files on the deployment branch too; they may differ from the application branch.
