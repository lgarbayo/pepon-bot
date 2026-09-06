# Signing your commits with GPG

PeponBot encourages (and, per `GOVERNANCE.md`/branch protection once enabled, may require) GPG-signed commits, in addition to the [DCO](../DCO) sign-off. GPG signing verifies *who* authored a commit; DCO sign-off certifies *the right to contribute it* — they're independent and this project uses both.

## 1. Generate a key (skip if you already have one)

```sh
gpg --full-generate-key
# Choose RSA and RSA, 4096 bits, an expiration you're comfortable with,
# and the name/email that matches your GitHub account and git config.
```

List your keys and copy the key ID (the part after `rsa4096/`):

```sh
gpg --list-secret-keys --keyid-format=long
```

## 2. Tell Git to use it

```sh
git config --global user.signingkey <YOUR_KEY_ID>
git config --global commit.gpgsign true
```

From now on, `git commit` signs automatically. To sign an individual commit explicitly (and combine with the DCO sign-off): `git commit -s -S`.

## 3. Add the key to GitHub

```sh
gpg --armor --export <YOUR_KEY_ID>
```

Paste the output into GitHub → **Settings → SSH and GPG keys → New GPG key**.

## 4. Verify

```sh
git log --show-signature -1
```

GitHub also shows a "Verified" badge next to signed commits once the matching public key is on your account.

## Troubleshooting

- **`gpg: signing failed: No pinentry`**: install a pinentry program (`pinentry-curses`, `pinentry-gtk-2`, or your platform's equivalent) and make sure `GPG_TTY` is exported in your shell profile: `export GPG_TTY=$(tty)`.
- **Commit shows "Unverified" on GitHub despite being signed locally**: the email in the key doesn't match a verified email on your GitHub account, or the public key hasn't been uploaded yet (step 3).
