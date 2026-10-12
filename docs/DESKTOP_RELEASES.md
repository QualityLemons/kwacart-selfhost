# Standalone KwaCart desktop edition

KwaCart is free. Standalone packages bundle Python, Django, the tool library,
templates and static assets. No Python install, terminal command, cloud account
or payment is required to use a desktop package.

## Preview security update

The initial `desktop-v1.0.0` preview was withdrawn on 12 October 2026 because
its generic media route bypassed private workshop export ownership checks.
Do not use that binary. Upgrade by replacing the app, not the data folder.
The corrected [desktop-v1.0.1 preview is published](https://github.com/QualityLemons/kwacart-selfhost/releases/tag/desktop-v1.0.1).
The [native build and publication run](https://github.com/QualityLemons/kwacart-selfhost/actions/runs/38259657879)
completed successfully on Windows, Intel Mac, Apple silicon Mac and Linux.
Its release assets are:

* `KwaCart-windows-x64.zip`
* `KwaCart-macos-intel.zip`
* `KwaCart-macos-apple-silicon.zip`
* `KwaCart-linux-x64.tar.gz`
* `kwacart-source.zip`
* `SHA256SUMS.txt`

The updated native checks verified anonymous visitors and unrelated signed-in
accounts to be denied private exports and uploads, while authorized owners can
still download their exports and view registered workshop attachments. All
four copied, read-only native installations also passed first-account, shutdown,
restart and update-backup checks. There
is no general-purpose `/media/` file server in the corrected desktop edition.
These downloads remain unsigned previews; automated native checks are not a
claim of signing, notarization or manual screen-reader verification.

## Download and open

Use only **[KwaCart's public releases](https://github.com/QualityLemons/kwacart-selfhost/releases)**.
Choose the package for your computer, not GitHub's automatically generated
“Source code” ZIP. Desktop previews are unsigned; they are not signed installers.
Do not turn off system security or bypass warnings for a copy from another site.

* **Windows 10/11, 64-bit:** extract the entire `KwaCart-windows-x64.zip`.
  Open the extracted KwaCart folder and double-click **KwaCart.exe**. Keep its
  `_internal` folder beside it. A security warning may appear for an unsigned
  preview. Only open a download you have verified from the public repository.
* **Mac, macOS 13 or newer:** choose `macos-apple-silicon` for an M-series Mac
  or `macos-intel` for an Intel Mac. Double-click the ZIP, then drag **KwaCart.app**
  to Applications and open it. An unsigned preview may be blocked by Gatekeeper.
  If you trust this exact public download, use the specific app's **Open Anyway**
  option in System Settings → Privacy & Security. Do not disable Gatekeeper.
* **Linux, 64-bit:** extract the `.tar.gz` in your file manager and open KwaCart.
  Your desktop must permit launching executables; some file managers require
  confirming **Allow executing file as program** in Properties. Built on Ubuntu
  22.04; requires a graphical desktop and compatible glibc/system libraries.

The native KwaCart window prepares your database and opens your default browser.
On first use, fill in the labelled email, password and confirmation fields.
That account is the local administrator. Email verification is not required.
Use **Open KwaCart** in the desktop window if the browser does not open.
Keep that window open while working. Click **Stop KwaCart** to finish.

KwaCart listens only on `127.0.0.1`, with a free port selected automatically.
Other devices cannot join this desktop edition. Use the source/server edition
for shared workshops. This protects against remote access but does not isolate
KwaCart from other programs or people using the same operating-system account.

## Your saved work

Your data is outside the application, so replacing the app does not erase it:

| Computer | Data folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\KwaCart` |
| Mac | `~/Library/Application Support/KwaCart` |
| Linux | `$XDG_DATA_HOME/kwacart` or `~/.local/share/kwacart` |

The window displays the exact path. It contains the database, uploaded media,
`.kwacart-local-key`, update backups, collected static assets and `desktop.log`.
Use your OS account permissions/disk encryption to protect it. Do not share
this folder, its key, logs or backups publicly. The launch address includes a
temporary first-setup ticket; do not share that address.

## Back up, update and restore

1. Stop KwaCart before backing up or updating.
2. Copy the **whole data folder** somewhere private. Keep the database, media
   and local key together. App downloads are not backups.
3. Download a newer desktop package from the public releases. Replace only
   the application folder/app, **not the data folder**.
4. Open the new app. When the app version changes, KwaCart automatically backs
   up the existing database, media and key under `backups` before migrations.
   It refuses older app versions rather than silently downgrading the data.
5. If startup fails, stop the app, keep a copy of the current data, and restore
   a complete backup plus its matching earlier app. See the backup's RESTORE.txt.

Backups are not automatically deleted. They may contain sensitive workshop data;
manage their storage and retention yourself. Source-launcher data is not
automatically imported: do not merge databases or regenerate a missing key.

## Build and release checks

Only `QualityLemons/kwacart-selfhost` may run the desktop release workflow.
The private workspace is never a build input. Export a clean allowlisted source
tree using `scripts/build_source_release.py`, then publish it to the public
repository without workspace history, credentials, databases or uploads.

The desktop workflow uses matching native Windows, Intel macOS, Apple silicon
macOS and Linux runners. It builds and tests the actual frozen executable:
native window, bundled subprocess, first account, host allowlist, asset/tool/
media routes, shutdown, restart, and a pre-migration update backup. All platforms
must pass before the optional public preview release is created. A Replit smoke
test is not proof of native installation behavior.

Run **Standalone desktop packages** from the public repository's Actions tab.
Leave **release** unchecked for build verification only. For a public preview,
select **release** and a new tag. Check the completed run and attached packages.
The release includes SHA-256 checksums and exact corresponding source.

Before a later application/schema release, increase the version in
`desktop/runtime.py` and the Mac bundle's version in `packaging/kwacart.spec`.
Use a matching new release tag. Never ship schema changes with an unchanged
application version: the backup/downgrade checks depend on that version.

AGPL `LICENSE`, `NOTICE`, dependency licences and the matching source ZIP are
inside every application bundle. Third-party resources keep their own rights.
Unsigned native checks are not equivalent to signing/notarization or manual
screen-reader/onboarding checks on a user's machine.
