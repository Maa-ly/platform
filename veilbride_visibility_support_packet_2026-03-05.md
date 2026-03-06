# GitHub Account Visibility Support Packet (veilbride)

Generated: 2026-03-05T13:14:50Z

## Summary
- The account `veilbride` is visible to itself but returns `404` to public and other authenticated users.
- This causes issues created by `veilbride` to be non-public (author-visible only).

## Repro Evidence (API)
All checks use `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`.

- public `GET /users/veilbride` -> `404`
  - request_id: `4B73:BDF66:7336B4:6868EC:69A981CB`
  - date: `Thu, 05 Mar 2026 13:14:51 GMT`
- public `GET /repos/veilbride/proof-media` -> `404`
  - request_id: `1627:330824:721428:676563:69A981CC`
  - date: `Thu, 05 Mar 2026 13:14:52 GMT`
- `kidinwhitegati` token `GET /users/veilbride` -> `404`
  - request_id: `1628:3A182:712BEC:66B8C4:69A981CC`
  - date: `Thu, 05 Mar 2026 13:14:53 GMT`
- `marvinayisi` token `GET /users/veilbride` -> `404`
  - request_id: `4B74:60780:6D542C:62FB4D:69A981CD`
  - date: `Thu, 05 Mar 2026 13:14:54 GMT`
- `veilbride` token `GET /users/veilbride` -> `200`
  - request_id: `4B75:BDF66:735476:6883B8:69A981CE`
  - date: `Thu, 05 Mar 2026 13:14:54 GMT`

Issue visibility split:
- `kidinwhitegati` token `GET /repos/PlatformNetwork/bounty-challenge/issues/23128` -> `404`
  - request_id: `1629:BDF66:735C3B:688B22:69A981CF`
  - date: `Thu, 05 Mar 2026 13:14:55 GMT`
- `veilbride` token `GET /repos/PlatformNetwork/bounty-challenge/issues/23128` -> `200`
  - request_id: `4B77:147C62:6E37F5:63B038:69A981D0`
  - date: `Thu, 05 Mar 2026 13:14:56 GMT`

Control sample:
- public `GET /repos/PlatformNetwork/bounty-challenge/issues/23136` -> `200`
  - request_id: `4B78:6B50D:714020:66D016:69A981D1`
  - date: `Thu, 05 Mar 2026 13:14:57 GMT`

## Web Symptoms
- `https://github.com/veilbride` returns `404` publicly.
- The same account is accessible when authenticated as `veilbride`.

## Impact
- Public bug submissions authored by `veilbride` are not visible to maintainers/public.
- This breaks external review and triage flows.

## Ready-to-send message to GitHub Support

Subject: `Account veilbride appears hidden to everyone except self (public 404 / self 200)`

Body:

Hello GitHub Support,

My account `veilbride` appears to be in an inconsistent visibility state:

1. Public and other authenticated users receive `404` for `GET /users/veilbride`.
2. My own token receives `200` for `GET /users/veilbride`.
3. Issues authored by `veilbride` in public repositories are visible to me but `404` for others/public.

This started recently on **March 5, 2026**.

Please review account visibility/moderation state for `veilbride` and restore normal public visibility.

Evidence with request IDs/timestamps:
- public `GET /users/veilbride` -> 404, request_id `4B73:BDF66:7336B4:6868EC:69A981CB`, `Thu, 05 Mar 2026 13:14:51 GMT`
- other token `GET /users/veilbride` -> 404, request_id `1628:3A182:712BEC:66B8C4:69A981CC`
- self token `GET /users/veilbride` -> 200, request_id `4B75:BDF66:735476:6883B8:69A981CE`
- issue visibility split:
  - other token `GET /repos/PlatformNetwork/bounty-challenge/issues/23128` -> 404, request_id `1629:BDF66:735C3B:688B22:69A981CF`
  - self token same endpoint -> 200, request_id `4B77:147C62:6E37F5:63B038:69A981D0`

Please let me know if you need additional headers or diagnostic output.

Thank you.

## Immediate hygiene (recommended)
- Rotate all Personal Access Tokens that were previously shared in logs/chats.
- Re-authenticate sessions after token rotation.
- Keep submission automation on a currently public account until `veilbride` visibility is restored.
