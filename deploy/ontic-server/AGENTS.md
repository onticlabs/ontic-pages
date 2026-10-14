Keep runtime settings in the Quadlet files and routing in the Caddy file. Declare state, authentication, health and rollback policy in app.toml; the general health checks need nothing else. Implement only the documented hooks. Secret names go in secrets.keys, values never go in this repository. tool.lock holds the one ontic-server commit this app is checked and deployed with; change it only after checking the app against the new commit, because `server <host> <app> check` fails while the running checkout is at another commit or has local changes.

Hooks (paths and deadlines in app.toml [hooks]) run on the box as root, from this folder as it is in the release, without the deploy lock, with APP, RELEASE, PREVIOUS_RELEASE, PHASE (the hook name) and ACTION (deploy, rollback, or restore when an automatic rollback runs) in the environment. Their output goes to the deploy log, so never print a secret.

| Hook | Runs | Nonzero exit or deadline |
|---|---|---|
| pre_stop | after the build, before the old release stops | aborts the deploy with nothing stopped; undo any partial change yourself |
| post_start | after every general check passed | fails the deploy like a failed check |
| watchdog | every 5 minutes, after the watchdog's general looks; observe only, never change anything | reported as a problem (incident, reminder, recovery) |

A failed notification never fails a deploy or triggers a rollback.
