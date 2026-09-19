import { useCallback, useEffect, useState } from "react";

/**
 * Fullscreen the map panel from the keyboard.
 *
 * The target is the whole dashboard shell, not the map panel. Fullscreening the
 * map alone drops its sibling rails out of the fullscreen subtree, so the
 * tactical list and the asset panel vanish exactly when an operator is most
 * likely to be presenting from the screen. Expanding the shell keeps the layout
 * intact and simply reclaims the browser chrome.
 *
 * The Fullscreen API is preferred, because then the operating system's own
 * fullscreen applies: browser chrome disappears and Escape behaves the way
 * people already expect. But the API is refused outright in some embedding
 * contexts — a preview pane, a kiosk frame, anywhere a Permissions-Policy
 * withholds it — and a shortcut that silently does nothing is worse than one
 * that does something useful. So a refusal falls back to expanding the panel to
 * fill the viewport, which is most of the value and always available.
 */

/** Ignore the shortcut while the operator is typing. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export interface FullscreenState {
  /** Expanded, by either route. */
  active: boolean;
  /** True when expansion is the CSS fallback rather than real fullscreen. */
  fallback: boolean;
  toggle: () => void;
}

export function useFullscreen(
  element: React.RefObject<HTMLElement | null>,
  key = "f",
): FullscreenState {
  /*
   * Climb from the supplied element to the shell that owns the whole layout.
   * The component holding the shortcut is the map, but the thing worth
   * expanding is everything around it, and falling back to the element itself
   * keeps this working if the shell class ever moves.
   */
  const targetFor = useCallback(
    (node: HTMLElement | null) => node?.closest<HTMLElement>(".app-frame") ?? node,
    [],
  );
  const [native, setNative] = useState(false);
  const [fallback, setFallback] = useState(false);

  const toggle = useCallback(() => {
    const node = targetFor(element.current);
    if (!node) return;

    if (document.fullscreenElement === node) {
      void document.exitFullscreen().catch(() => {
        /* Already exiting, or the document lost the request. */
      });
      return;
    }
    if (fallback) {
      setFallback(false);
      return;
    }

    if (!document.fullscreenEnabled) {
      setFallback(true);
      return;
    }

    /*
     * A refusal arrives two different ways. The spec says the call returns a
     * rejected promise, but a Permissions-Policy denial throws synchronously
     * before a promise exists — so `.catch()` alone silently misses it and the
     * shortcut appears to do nothing. Both paths land on the fallback.
     */
    try {
      const request = node.requestFullscreen();
      if (request && typeof request.catch === "function") {
        request.catch(() => setFallback(true));
      }
    } catch {
      setFallback(true);
    }
  }, [element, fallback, targetFor]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Escape leaves the fallback, mirroring what it does for real fullscreen.
      if (event.key === "Escape") {
        setFallback(false);
        return;
      }
      if (event.key.toLowerCase() !== key) return;
      // Leave modified presses to the browser and the OS.
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;
      event.preventDefault();
      toggle();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [key, toggle]);

  // Escape and the browser's own controls exit fullscreen without telling us,
  // so the flag follows the document rather than the toggle.
  useEffect(() => {
    const onChange = () => {
      const isNative =
        document.fullscreenElement !== null &&
        document.fullscreenElement === targetFor(element.current);
      setNative(isNative);
      if (isNative) setFallback(false);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [element, targetFor]);

  /*
   * The fallback class goes on the shell, which React does not own here, so it
   * is applied directly. The native path needs nothing: `:fullscreen` already
   * matches whatever element the browser promoted.
   */
  useEffect(() => {
    const node = targetFor(element.current);
    if (!node) return undefined;
    node.classList.toggle("ark-fullscreen-fallback", fallback);
    return () => node.classList.remove("ark-fullscreen-fallback");
  }, [element, fallback, targetFor]);

  return { active: native || fallback, fallback, toggle };
}
