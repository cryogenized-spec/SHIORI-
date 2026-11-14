# M2.7 — stable, external debug signing (pre-release rehearsal only)

**Status: optional development-only configuration. Not a production signing pipeline or release approval.**

SHIORI's GitHub CI builds use ephemeral debug signing by default. That is
sufficient for disposable emulator UI testing but may prevent an in-place
upgrade across different workflow runs. Never uninstall a task-bearing app
just to work around an Android signing mismatch: uninstall can delete
app-private SQLite databases and the offline WebView store.

## Build with your own stable development certificate

Use a **disposable emulator/profile** and a keystore held outside the source
repository. Create the keystore locally with Android's `keytool` (answer
password prompts interactively, do not include secrets in Git history):

```bash
mkdir -p "$HOME/.config/shiori-private"
chmod 700 "$HOME/.config/shiori-private"
keytool -genkeypair \
  -keystore "$HOME/.config/shiori-private/dev-signing.jks" \
  -alias shiori-local-dev -keyalg RSA -keysize 3072 \
  -validity 3650
```

Then configure your **local shell** with all four required variables, using
secret-input methods rather than embedding passwords in scripts, CLI
arguments, GitHub comments or logs. For example:

```bash
export SHIORI_DEV_KEYSTORE_PATH="$HOME/.config/shiori-private/dev-signing.jks"
export SHIORI_DEV_KEY_ALIAS="shiori-local-dev"
read -rsp "Keystore password: " SHIORI_DEV_KEYSTORE_PASSWORD; echo
export SHIORI_DEV_KEYSTORE_PASSWORD
read -rsp "Key password: " SHIORI_DEV_KEY_PASSWORD; echo
export SHIORI_DEV_KEY_PASSWORD

# For baseline, omit SHIORI_DEV_VERSION_CODE (defaults to 5);
# for the later candidate, set it to 6 or higher.
gradle -p apps/android :app:assembleDebug
```

Run the existing pinned Rust NDK build beforehand, as described in
`apps/android/README.md`. If the keystore has the same key password as the
store password, the second secret prompt should use that value.

The Gradle contract is deliberately restrictive:

- All four signing variables are required together; a partial setup fails.
- The keystore must be an existing file **outside** the repository.
- `SHIORI_DEV_VERSION_CODE` must be a positive integer at least 5 and
  requires the explicit stable signer. The baseline versionCode remains 5
  when no override is provided.
- Only the **debug** build type can use this optional configuration. Normal
  CI without the variables keeps Android's default debug signer.
- No signing material is added to source control, GitHub Actions artifacts,
  application assets, documentation examples or the debug APK manifest.
  The evidence manifests contain only the public certificate SHA-256.

## Required preflight and test scope

Build baseline and candidate from distinct source commits using the same
externally held certificate, with candidate versionCode greater than
baseline. Run `tools/android/compare_debug_upgrades.py` using each APK and
its independently generated evidence manifest, and supply Android SDK paths
for `aapt` and `apksigner`.

**A passing preflight is not equivalent to a successful in-place upgrade.**
The next gate is a verified `adb install -r` rehearsal on a disposable
emulator or isolated Android test user with synthetic records, followed by
data persistence checks and explicit physical handset acceptance. Never
test a signing change by uninstalling the existing real-data installation.

Production publication remains blocked on a dedicated release signing
process, securely stored long-lived keys, verified recovery, device
keyboard/gesture QA, document provider fault testing, security review, and
explicit owner authorization.
