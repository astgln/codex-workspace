# Codex Web UI attribution

Derived from https://github.com/LuSeptem/codex-webui at commit `421f18acdf6928da6e35611d9d1f53443fcb0c34`.
MIT license: [full notice](licenses/codex-webui-MIT.txt).

Imported rendering components and utilities:
- `src/components/events/Markdown.tsx`
- `src/components/events/AgentMessageCard.tsx`
- `src/components/events/UserMessageCard.tsx`
- `src/components/events/FileChangeCard.tsx`
- `src/components/events/PlanUpdateCard.tsx`
- `src/components/events/ErrorCard.tsx`
- `src/components/diff/DiffViewerDialog.tsx`
- `src/components/ui/Toaster.tsx`
- `src/components/i18n/LanguageProvider.tsx`
- `src/stores/toast.tsx`
- `src/types/api.ts`
- `src/lib/i18n/messages.ts`
- `src/lib/codex/user-message.ts`
- `src/lib/utils/format.ts`
- `src/lib/utils/diff.ts`
- `src/lib/utils/highlight.ts`
- `src/lib/utils/cn.ts`

`src/upstream.css` and Tailwind design tokens also derive from upstream.
The app shell and cloud transport are adapted for this project. Local filesystem,
process execution, settings, and session-scanning APIs are not shipped.
