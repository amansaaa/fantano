"use client";

/**
 * shown when a page crashes, e.g. MySQL isn't running. instead of next's default error screen,
 * it says what happened in plain words and offers "Try again" (re-runs the page's queries).
 * the real error goes to the browser console; in production next hides its details and only
 * passes an id (error.digest) that matches the server log.
 *
 * error boundaries have to be client components, hence "use client".
 */

import Link from "next/link";
import { useEffect } from "react";

type Props = {
  error: Error & { digest?: string };
  retry: () => void;
};

export default function PageError({ error, retry }: Props) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
      <h1 className="text-2xl font-semibold text-ink">Something went wrong</h1>
      <p className="text-muted">This page couldn’t load its data. It’s usually temporary.</p>
      <div className="mt-2 flex items-center gap-4">
        <button
          type="button"
          onClick={() => retry()}
          className="rounded-full border border-ink/80 px-5 py-2 text-sm text-ink transition-colors hover:bg-ink hover:text-white"
        >
          Try again
        </button>
        <Link href="/" className="text-sm text-muted hover:text-ink">
          ← Home
        </Link>
      </div>
    </main>
  );
}
