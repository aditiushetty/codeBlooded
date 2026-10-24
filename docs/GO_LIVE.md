# Taking the Meta app live (TODO 22)

In development mode, Instagram only shows Counterpart the comments and DMs of accounts with a role on the app. WhatsApp only sends to 5 verified numbers. Once the app is Live, every customer counts. These steps happen in Meta's dashboards and need the owner's documents and decisions, so nobody can finish them from code. Expect days to weeks.

App: **Counterpart** (`1283719630565611`), Instagram app **Counterpart-IG** (`1155743350218695`), portfolio **Counterpartdemo** (`1104810049104981`).

## 1. Public pages (built 2026-10-24)
Deploy the frontend (Vercel), then use these:
- Privacy policy: `https://<site>/privacy`
- Terms of service: `https://<site>/terms`
- User data deletion: `https://<site>/data-deletion`. Data deletion **callback** and Deauthorize callback: `https://<site>/api/public/meta/data-deletion`. Meta signs it with the app secret; Counterpart deletes the Instagram connection and its data, then returns a confirmation code that the page above checks.
- Before going live, set `NEXT_PUBLIC_CONTACT_EMAIL` on Vercel. The pages show it as the contact address.

Where they go: **App settings → Basic** (Privacy policy URL, Terms of Service URL, User data deletion, App icon 1024×1024, Category: Business and pages). Then **Instagram → API setup with Instagram login → Business login settings** (Deauthorize and Data deletion request callback URLs).

## 2. Business Verification (portfolio owner)
business.facebook.com → Settings → Security centre → **Start verification**. You need the legal business name, address and phone, plus one document: GST certificate, Udyam registration, shop and establishment licence, or a utility bill in the business's name. Meta may also check a domain or phone. It takes about 2 to 10 working days.

## 3. App Review: permissions and what to say
Go to **App Review → Permissions and features**, and for each permission request **Advanced access**. Each one needs a short description and a screencast showing the real flow (screen-record the local app plus Instagram on a phone).

| Permission | Why Counterpart needs it | Screencast shows |
|---|---|---|
| `instagram_business_basic` | Show the connected account's username and its recent posts so the owner can link them to campaigns. | Channels page → connect → username shown → "Link one I posted" list. |
| `instagram_business_content_publish` | Publish an approved offer post the owner has checked, with its post code in the caption. | Campaign → approve post → "Post to Instagram" → the post on Instagram. |
| `instagram_business_manage_insights` | Show reach, likes, saves and shares next to counter redemptions per post. | Campaign Performance → Instagram numbers. |
| `instagram_business_manage_comments` | Read comments as reviews, let the owner reply under a comment, and add the "Comment CODE" line on older posts. | Customers page → comment shown and sorted → reply sent → reply under the comment. |
| `instagram_business_manage_messages` | Answer a customer who comments or DMs "CODE" with their personal one-time code (private reply / DM reply inside 24 h). | Tester comments CODE → private message arrives with code → counter redeems it. |
| `whatsapp_business_messaging` | Reply to a customer who messages a post's code with their personal code; STOP/START opt-out. | Customer sends code on WhatsApp → reply with code → counter. |

The reviewer needs a way in. Give them the demo login (**Try the demo**), plus a test Instagram account added as a tester with its password in the review notes, entered by the owner.

## 4. Switch to Live
After approval, go to **Publish** (left menu) and switch the app to **Live**. Remove tester-only notes from the Customers page copy if wanted. The hidden-comments count (`comments_hidden`) should drop to 0 by itself.
