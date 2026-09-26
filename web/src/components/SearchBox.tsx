"use client";

/**
 * the pill-shaped search box with its ARTISTS dropdown. used big on the home page and small at
 * the top of the artist page.
 *
 * steps, on every keystroke:
 *   1. wait until typing pauses for a moment, so "sza" is one request and not three
 *   2. ask GET /api/search?q=... and cancel the previous request if it's still running
 *   3. show the matches; clicking one (or arrow keys + enter) opens /artist/{id}
 *
 * usage:
 *   <SearchBox size="large" autoFocus />   // home page
 *   <SearchBox size="small" />             // artist page header
 *
 * reads: GET /api/search
 */

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import type { SearchResult } from "@/lib/types";

// how long typing has to pause before we search
const TYPING_PAUSE_MS = 150;
const RESULT_PHOTO_PX = 36;

type Props = {
  size: "large" | "small";
  autoFocus?: boolean;
};

type Status = "idle" | "loading" | "done" | "error";

export default function SearchBox({ size, autoFocus = false }: Props) {
  const router = useRouter();
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);

  const [typed, setTyped] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [isOpen, setIsOpen] = useState(false);
  // which result the arrow keys are on (-1 = none)
  const [activeIndex, setActiveIndex] = useState(-1);

  const searchText = typed.trim();

  // --- searching as you type ---

  useEffect(() => {
    if (!searchText) {
      return;
    }

    const request = new AbortController();
    const timer = setTimeout(async () => {
      setStatus("loading");
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(searchText)}`, {
          signal: request.signal,
        });
        if (!response.ok) {
          throw new Error(`search failed with ${response.status}`);
        }
        setResults(await response.json());
        setActiveIndex(-1);
        setStatus("done");
      } catch (error) {
        // a newer keystroke cancelled this request, which is expected and not an error
        if (request.signal.aborted) {
          return;
        }
        console.error(error);
        setStatus("error");
      }
    }, TYPING_PAUSE_MS);

    // runs when searchText changes again: drop the pending timer and the running request
    return () => {
      clearTimeout(timer);
      request.abort();
    };
  }, [searchText]);

  // --- closing the dropdown on an outside click ---

  useEffect(() => {
    function closeIfOutside(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", closeIfOutside);
    return () => document.removeEventListener("mousedown", closeIfOutside);
  }, []);

  // --- keyboard: arrows move, enter opens, escape closes ---

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setIsOpen(false);
      return;
    }
    if (!results.length) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIsOpen(true);
      setActiveIndex((index) => (index + 1) % results.length);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => (index <= 0 ? results.length - 1 : index - 1));
      return;
    }
    if (event.key === "Enter") {
      // enter with nothing highlighted opens the top result
      const chosen = results[Math.max(activeIndex, 0)];
      router.push(`/artist/${chosen.id}`);
    }
  }

  const isLarge = size === "large";
  const showDropdown = isOpen && searchText !== "" && status !== "idle";

  return (
    <div ref={boxRef} className="relative w-full">
      <div
        className={`flex items-center gap-3 rounded-full border border-ink/80 bg-white transition-shadow focus-within:shadow-[0_0_0_4px_rgba(17,17,20,0.06)] ${
          isLarge ? "h-14 px-6" : "h-11 px-5"
        }`}
      >
        <SearchIcon className={isLarge ? "size-5" : "size-4"} />
        <input
          type="text"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          autoFocus={autoFocus}
          placeholder="Search an artist…"
          aria-label="Search an artist"
          role="combobox"
          aria-expanded={showDropdown}
          aria-controls={listId}
          aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          autoComplete="off"
          spellCheck={false}
          className={`w-full bg-transparent text-ink outline-none placeholder:text-muted ${
            isLarge ? "text-lg" : "text-sm"
          }`}
        />
      </div>

      {showDropdown && (
        <div className="absolute inset-x-0 top-full z-20 mt-2 overflow-hidden text-left rounded-2xl border border-line bg-white py-3 shadow-[0_12px_40px_-12px_rgba(17,17,20,0.18)]">
          <p className="pb-2 text-center text-[11px] font-medium tracking-[0.2em] text-label">ARTISTS</p>

          {status === "error" && <p className="px-5 py-3 text-sm text-muted">Search isn’t working right now.</p>}

          {status !== "error" && results.length === 0 && (
            <p className="px-5 py-3 text-sm text-muted">
              {status === "loading" ? "Searching…" : `No reviewed artist matches “${searchText}”.`}
            </p>
          )}

          <ul id={listId} role="listbox">
            {results.map((artist, index) => (
              <li key={artist.id} id={`${listId}-${index}`} role="option" aria-selected={index === activeIndex}>
                <Link
                  href={`/artist/${artist.id}`}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={`flex items-center gap-3 px-5 py-2 ${index === activeIndex ? "bg-placeholder" : ""}`}
                >
                  <ArtistThumb url={artist.image_url} name={artist.name} />
                  <span className="flex-1 truncate text-[15px] text-ink">{artist.name}</span>
                  <span className="shrink-0 text-xs text-muted">
                    {artist.review_count} {artist.review_count === 1 ? "review" : "reviews"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// --- small pieces ---

/** the artist's photo in a result row, or a gray square when deezer had none. */
function ArtistThumb({ url, name }: { url: string | null; name: string }) {
  if (!url) {
    return <span className="size-9 shrink-0 rounded-md bg-placeholder" />;
  }
  return (
    <Image
      src={url}
      alt={name}
      width={RESULT_PHOTO_PX}
      height={RESULT_PHOTO_PX}
      className="size-9 shrink-0 rounded-md object-cover"
    />
  );
}

function SearchIcon({ className }: { className: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`shrink-0 text-ink ${className}`} aria-hidden>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" strokeLinecap="round" />
    </svg>
  );
}
