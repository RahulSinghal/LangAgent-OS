### UI Test Cases (Manual)

Use this checklist to validate the UI end-to-end.

---

### Preconditions

- API running:

```bash
python -m uvicorn app.main:app --reload --port 8001
```

- Open UI: `http://localhost:8001/`

---

### Test Case 1 — UI loads

- **Step**: Open `/`
- **Expected**: AgentOS UI renders (top bar, chat area, “+” button).
  - Projects dropdown is visible.

---

### Test Case 1B — Load saved history

- **Precondition**: You have existing projects with saved messages.
- **Step**: Select a project from the **Projects** dropdown (or click **Load history** after selecting).
- **Expected**: The chat panel is replaced with the saved messages for that project in chronological order.

---

### Test Case 2 — Upload a text document via “+”

- **Step**: Click **“+”** and select a `.txt` file.
- **Expected**:
  - A message appears: “Extracted N chars…”
  - The “Document text” box is populated with the extracted text.

---

### Test Case 3 — Upload a PDF via “+”

- **Step**: Click **“+”** and select a `.pdf`.
- **Expected**:
  - Extracted text appears in “Document text”
  - If PDF is scanned-image-only: extracted text may be empty (OCR not enabled).

---

### Test Case 4 — Start run with document + message

- **Step**: Type a message and click **Send** (with document text present).
- **Expected**:
  - UI shows “Run started (id=…)”
  - After clicking **Refresh**, “Next question” is populated or run proceeds to approvals.

---

### Test Case 5 — Hosting preference routes server-details approval (client-hosted)

- **Step**: Start a run with a message that clearly indicates client hosting, e.g.
  - “Client will host on their own server.”
- **Expected**:
  - When PRD gate is reached, pending approvals include:
    - `prd`
    - `server_details_client`

---

### Test Case 6 — Hosting preference routes server-details approval (vendor-hosted)

- **Step**: Start a run with a message:
  - “We can upload it on your server / deploy on your server.”
- **Expected**:
  - Pending approvals include:
    - `prd`
    - `server_details_infra`

---

### Test Case 7 — Multiple pending approvals show as a list

- **Step**: When status becomes `waiting_approval`, click **Refresh**.
- **Expected**:
  - Approval panel shows multiple buttons (one per pending approval), e.g.
    - `#123 • prd • pending`
    - `#124 • server_details_client • pending`

---

### Test Case 8 — Resolve approvals and observe progression

- **Step**:
  - Click a pending approval item in the list.
  - Add comments (optional).
  - Click **Approve**.
  - Repeat until no pending approvals remain.
- **Expected**:
  - After each resolution, a system message confirms it.
  - Run resumes and progresses when all required approvals are approved.

---

### Notes / limitations

- Image uploads are accepted but currently return empty extracted text (no OCR/vision).

