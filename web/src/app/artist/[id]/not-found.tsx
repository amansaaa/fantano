/**
 * shown for /artist/{id} when that artist doesn't exist (or the id isn't a number).
 */

import Link from "next/link";

import SearchBox from "@/components/SearchBox";

export default function ArtistNotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-6 px-4 text-center">
      <h1 className="text-2xl font-semibold text-ink">No artist here</h1>
      <p className="text-muted">This link doesn’t match any artist. Try searching instead.</p>
      <div className="w-full">
        <SearchBox size="large" />
      </div>
      <Link href="/" className="text-sm text-muted hover:text-ink">
        ← Home
      </Link>
    </main>
  );
}
