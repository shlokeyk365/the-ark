import { useEffect, useId, useRef, type FormEvent } from "react";
import { createPortal } from "react-dom";

import { ShellIcon } from "./ShellIcon";

interface CommandChatOverlayProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Static visual fixture for the Spotlight-style command chat.
 * The intelligence owner should replace this with live thread state.
 */
const DUMMY_THREAD = [
  {
    role: "user" as const,
    text: "Which community becomes isolated first?",
  },
  {
    role: "assistant" as const,
    text: "Nakkhu Riverbend loses a safe path first under the current flood frames. Isolation is modeled around +21h if Nakkhu East Bridge stays open.",
  },
];

const DUMMY_SUGGESTIONS = [
  "Compare Plan A, B, and C",
  "Hospital access at +12h",
  "What if Nakkhu East Bridge fails?",
];

export function CommandChatOverlay({ open, onClose }: CommandChatOverlayProps) {
  const titleId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const previous = document.activeElement;
    const frame = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // Partner: send the prompt to the command chat backend.
  };

  const fillSuggestion = (prompt: string) => {
    if (!inputRef.current) return;
    inputRef.current.value = prompt;
    inputRef.current.focus();
  };

  return createPortal(
    <div className="command-chat-root">
      <button
        className="command-chat-backdrop"
        type="button"
        aria-label="Dismiss command chat"
        onClick={onClose}
      />
      <div
        className="command-chat-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="command-chat-shine" aria-hidden="true" />
        <div className="command-chat-spec" aria-hidden="true" />

        <form className="command-chat-search" onSubmit={onSubmit}>
          <ShellIcon name="search" size={18} />
          <h2 id={titleId} className="sr-only">
            Ask ARK
          </h2>
          <input
            ref={inputRef}
            name="prompt"
            type="text"
            autoComplete="off"
            spellCheck={false}
            placeholder="Ask ARK about this incident…"
            aria-label="Ask ARK"
          />
          <kbd className="command-chat-esc">esc</kbd>
          <button
            ref={closeButtonRef}
            className="command-chat-close"
            type="button"
            aria-label="Close command chat"
            onClick={onClose}
          >
            <ShellIcon name="x" size={14} />
          </button>
        </form>

        <div className="command-chat-body">
          <ol className="command-chat-thread" aria-label="Conversation preview">
            {DUMMY_THREAD.map((message, index) => (
              <li
                key={`${message.role}-${index}`}
                className={`command-chat-message ${message.role}`}
              >
                <span className="command-chat-role">
                  {message.role === "user" ? "You" : "ARK"}
                </span>
                <p>{message.text}</p>
              </li>
            ))}
          </ol>

          <div className="command-chat-suggestions">
            <span className="command-chat-hint">Suggested</span>
            {DUMMY_SUGGESTIONS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => fillSuggestion(prompt)}
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>

        <footer className="command-chat-footer">
          <span>AI interpretation · visual dummy</span>
          <span>Not operational truth</span>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
