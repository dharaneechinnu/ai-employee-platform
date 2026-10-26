# How our server connects to Google

A plain-English walkthrough of what happens between this server and
Google when someone clicks **Connect Google Workspace**: what is
stored, what can go wrong, and what still has to be done before many
people can use it.

Microsoft 365 works the same way end to end. Where it differs, it is
called out.

---

## 1. The thing to understand first

Our server never learns anyone's Google password. It never sees it, is
never sent it, and could not use it if it were.

What it gets instead is a **refresh token**: a long-lived voucher,
issued by Google, that says *"the holder of this may do these specific
things to this one account until it is revoked."* Google issues it only
after the person has signed in on Google's own page and read a list of
exactly what they are agreeing to.

Three consequences worth keeping in mind:

- The person can **revoke it at any time** from their Google account,
  without telling us. Our side has to cope with that, not assume it
  away.
- It is **scoped**. A token that can read Gmail cannot delete the
  account or change the password, because we never asked for that.
- It is a **secret of the same weight as a password**, so it is
  encrypted at rest and never enters a model's context.

---

## 2. What has to exist before any of this works

An OAuth flow needs a registered **application**: a `client_id` and
`client_secret` issued by Google to *somebody*. This is the part people
usually miss: you cannot connect Gmail with code alone. Someone has to
register an app in Google Cloud first.

This server accepts that registration from either side, and checks
in this order:

| Order | Source | Who sets it up | Whose name is on the consent screen |
|---|---|---|---|
| 1 | The person's own app | The person, under **Connections** | Theirs |
| 2 | The platform's app | The Platform Admin, once, under **One-click sign-in** | The platform's |
| 3 | Environment variables | Whoever deploys the server | The platform's |

A person who registers their own app wins over the platform's, because
registering one is a deliberate act. A person who does nothing gets the
platform's app if one exists. **Neither path blocks the other**, and
the Platform Admin is not in the way of anyone's setup unless they want
to be.

In code this is `resolve_client()` in
[oauth_providers.py](../backend/app/services/oauth_providers.py).

---

## 3. The flow, step by step

```
  The person               Our API                 Google              Our worker
        │                     │                      │                     │
   1    │ Connect Google ───▶ │                      │                     │
        │                     │                      │                     │
   2    │ ◀── redirect URL ── │ builds it with the   │                     │
        │                     │ client_id + scopes   │                     │
        │                     │ + a signed state     │                     │
   3    │ ─────────── browser goes to Google ──────▶ │                     │
        │                     │                      │                     │
   4    │        signs in and reads the consent screen                     │
        │                     │                      │                     │
   5    │ ◀───── Google sends the browser back with a short-lived code     │
        │                     │                      │                     │
   6    │                     │ ── code + secret ──▶ │                     │
   7    │                     │ ◀── access token ─── │                     │
        │                     │     + refresh token  │                     │
        │                     │                      │                     │
   8    │                     │ encrypt + store      │                     │
        │                     │                      │                     │
   9    │                     │          later, a run needs Gmail:         │
        │                     │ ◀──────────────────────────────────────────│
  10    │                     │ ── refresh ─────────▶│                     │
  11    │                     │ ◀── fresh access ────│                     │
  12    │                     │ ───── calls Gmail API, returns result ────▶│
```

**Step 1: what to share.** Before signing in, the person chooses which
parts of Google the assistant may use (Gmail, Calendar, Drive, Sheets)
and, for each, whether it may only read or also edit. Leaving it as is
gives the default: Gmail and Calendar with edit, Drive read only. The
scopes in step 2 are worked out from that choice.

**Step 2: the state.** The `state` parameter is a signed token naming
the person who started the sign-in, with a ten-minute expiry. It is how
step 5 knows whose sign-in this is without keeping a table of
half-finished attempts, and it stops someone pasting their own callback
URL to attach a Google account to somebody else. Signed, not guessed:
see `sign_for()` in [signed.py](../backend/app/core/signed.py).

**Step 2: `access_type=offline` and `prompt=consent`.** Google only
returns a refresh token when both are present. Without them the flow
appears to work and then stops working an hour later, which is a
miserable bug to chase.

**Step 6: the code is exchanged on the server.** The `client_secret`
never reaches the browser.

**Step 8: what is stored.** The refresh token, the access token and
its expiry, encrypted with AES-GCM under a key derived for *that
person's account*, with the account id as additional authenticated
data. A ciphertext lifted from one person's row cannot be decrypted as
anyone else's. See [crypto.py](../backend/app/core/crypto.py). The
permissions Google actually granted are stored too, so a tool that
needs a permission the person did not give is refused with a clear
message.

**Step 10: refresh.** Access tokens last about an hour; refresh tokens
last until revoked. The worker refreshes with a margin rather than
waiting for a 401, and on failure marks the connection
`needs_reconnect` with a message the person can act on, rather than
failing the run with a stack trace.

---

## 4. What we ask for, and why that much

Each part of Google has a read scope and, where a tool can change
something, an edit scope. We ask only for the levels the person chose.

| Part | Read scope | Edit scope | Tools |
|---|---|---|---|
| Gmail | `gmail.readonly` | `gmail.modify` | `gmail_search`, `gmail_read`, `gmail_create_draft`, `gmail_send` |
| Calendar | `calendar.events.readonly` | `calendar.events` | `google_calendar_list`, `google_calendar_create` |
| Drive | `drive.readonly` | none | `google_drive_search`, `google_drive_read` |
| Sheets | `spreadsheets.readonly` | `spreadsheets` | `sheets_create`, `sheets_read`, `sheets_append_rows`, `sheets_update_cells` |
| Who this is | `openid`, `email`, `profile` | | so the screen can show *which* account is connected |

Two deliberate omissions. `gmail.modify` **cannot permanently delete**
mail; that needs `https://mail.google.com/`, which we do not request.
Drive is **read-only**, so the assistant can find a document but never
change or remove one.

The catalogue of parts, levels and scopes is in
[services.py](../backend/app/agent/services.py). A Platform Admin can
also close a part (for example Sheets edit) for everyone or for one
account; that check happens before any tool runs.

Narrow scopes are not only good hygiene here; they are the difference
between a short verification review and a long one (§6).

---

## 5. Personal Gmail and Workspace are the same flow

A `@gmail.com` account and a Workspace account both sign in through the
identical flow and produce the identical kind of token. Nothing in the
code branches on it.

Two differences that are not ours to control:

- A **Workspace administrator** can block third-party apps for their
  whole domain, or require admin approval first. If that is set, the
  person sees Google's "admin has disabled" screen and there is nothing
  our side can do but report it clearly.
- A Workspace admin can **domain-wide delegate** instead, which skips
  per-user consent entirely. That is a different and much heavier
  integration; we have deliberately not built it, because it hands one
  credential access to every mailbox in a domain at once.

---

## 6. The three things that will bite

These are the real-world constraints, and they are the reason this
document exists.

### 6.1 In "Testing" mode, refresh tokens die after 7 days

A Google Cloud project whose OAuth consent screen is set to **External
→ Testing** issues refresh tokens that **expire in seven days**. Every
connection silently stops working a week after it was made, and the
cause is not obvious from our logs.

> Verified against Google's own documentation: a project with external
> user type and publishing status "Testing" is issued refresh tokens
> expiring in 7 days. It does not apply if the only scopes are name,
> email and profile, which is not our case, because we ask for Gmail.

**What to do:** set the publishing status to **In production**. That is
a setting, not an approval, but see the next point for what production
status then requires.

### 6.2 Gmail scopes are "restricted" and need verification

`gmail.readonly` and `gmail.modify` are restricted scopes. An app in
production asking for them and serving people outside its own
organisation must go through Google's OAuth verification, which for
restricted scopes also means an annual third-party security assessment
(CASA). This takes weeks and costs money.

Until that is done, an unverified app shows a warning screen and is
capped at a small number of users.

**What this means in practice:**

- **For a demo:** your own Google account, your own project, Testing
  mode. Everything works. Just know the 7-day clock is running.
- **For one person, or a few:** each person registers the app in their
  own Google Cloud project (path 1 in §2). An app used only by its own
  developer, or only inside its own Workspace organisation, does not
  need the external verification. This is the main reason a person can
  bring their own app.
- **For many people on one shared app:** the platform registers one
  app and completes verification and CASA. That is a project in itself,
  with a budget.

### 6.3 A password change revokes the token

Google invalidates refresh tokens with Gmail scopes when the person
changes their account password. This is correct behaviour and we cannot
avoid it; the connection simply needs making again. It is handled the
same way as revocation: mark `needs_reconnect`, say so plainly, do not
fail silently.

---

## 7. What someone actually has to do in Google Cloud

For a person registering their own app (§2, path 1):

1. **Create a project** at <https://console.cloud.google.com>.
2. **Enable the APIs** you will use: Gmail API, Google Calendar API,
   Google Drive API, Google Sheets API.
3. **Configure the OAuth consent screen**: internal if everyone who
   will connect is in the same Workspace, external otherwise. Add the
   scopes in §4 that you plan to use.
4. **Create credentials** → OAuth client ID → *Web application*.
5. **Add the redirect URI exactly as our Connections page shows it.**
   It must match to the character, including `http` vs `https` and any
   trailing path. A mismatch here is the single most common cause of a
   failed sign-in, which is why the page shows the string with a copy
   button instead of describing it.
6. **Paste the client ID and secret** into Connections.
7. If external: set publishing status to **In production** (§6.1).

---

## 8. What is built, and what is not

**Built and tested**

- Three-level app resolution: the person's own app → the platform's →
  environment variables
- The full authorisation-code flow with a signed, short-lived state
- A choice of parts and levels (read or edit) when connecting, with
  only the matching scopes requested
- Encrypted-at-rest refresh tokens, scoped to one person, with no read
  path to any credential
- Automatic access-token refresh with a margin, and a clear
  `needs_reconnect` state when it fails
- Twelve Google tools (including four for Sheets) and eight Microsoft
  tools, each declaring its own side effect so Permissions can gate it
- A Platform Admin screen to register the shared app, and a
  Connections screen where a person registers their own
- Platform Admin controls to open or close a connection, or one part of
  an app, for everyone or for one account

**Not built, deliberately**

- **Domain-wide delegation** (§5): one credential reaching every
  mailbox in a domain is a larger blast radius than this product
  needs.
- **Google's verification and CASA assessment**: a commercial process,
  not a coding task. The bring-your-own-app path exists so the product
  is usable before it is done.
- **Push notifications** (Gmail watch / Graph subscriptions): today the
  assistant reads mail when a chat or a scheduled agent tells it to,
  rather than reacting to arrival. This is the natural next step for
  event-triggered work.

---

## 9. If it goes wrong, look here first

| What you see | Almost always |
|---|---|
| `redirect_uri_mismatch` | The URI in Google Cloud is not character-identical to the one on the Connections page |
| Works, then fails ~1 hour later | No refresh token was issued: `access_type=offline` and `prompt=consent` missing |
| Works, then fails after ~7 days | Consent screen still in **Testing** (§6.1) |
| "Google hasn't verified this app" | Unverified app with restricted scopes (§6.2) |
| `admin has disabled this app` | The Workspace administrator blocks third-party apps (§5) |
| Stops after the person changed their password | Expected; reconnect (§6.3) |
| `invalid_client` | Client ID and secret are from different projects, or the secret was rotated in Google Cloud |
| A tool says the permission was not granted | The person connected without that part or level; connect again and tick it |
