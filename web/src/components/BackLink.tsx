"use client";

/**
 * "← Back" at the top of the artist page. it goes to the previous page (another artist, or
 * the home page). if this page was opened directly (no history), it goes home instead.
 */

import { useRouter } from "next/navigation";

export default function BackLink() {
  const router = useRouter();

  function goBack() {
    if (window.history.length > 1) {
      router.back();
      return;
    }
    router.push("/");
  }

  return (
    <button type="button" onClick={goBack} className="shrink-0 text-sm text-muted transition-colors hover:text-ink">
      ← Back
    </button>
  );
}
