/**
 * a square image with rounded corners: an artist photo or a song cover. when deezer had no
 * image, an artist gets a gray square with a person outline and a cover gets a plain gray square.
 *
 * usage:
 *   <ArtistPhoto url={artist.image_url} name="SZA" sizePx={280} className="w-full rounded-2xl" />
 *   <ArtistPhoto url={track.cover_url} name="Kill Bill" sizePx={64} kind="cover" className="size-16 rounded-md" />
 *
 * `sizePx` is the biggest it's ever shown, so next/image fetches a sharp enough version.
 */

import Image from "next/image";

type Props = {
  url: string | null;
  name: string;
  sizePx: number;
  className: string;
  kind?: "artist" | "cover";
  preload?: boolean;
};

export default function ArtistPhoto({ url, name, sizePx, className, kind = "artist", preload = false }: Props) {
  if (url) {
    return (
      <Image
        src={url}
        alt={name}
        width={sizePx}
        height={sizePx}
        preload={preload}
        className={`aspect-square bg-placeholder object-cover ${className}`}
      />
    );
  }

  return (
    <div role="img" aria-label={name} className={`flex aspect-square items-center justify-center bg-placeholder ${className}`}>
      {kind === "artist" && (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.2" className="w-2/5 text-muted/60" aria-hidden>
          <circle cx="12" cy="8" r="4" />
          <path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7" strokeLinecap="round" />
        </svg>
      )}
    </div>
  );
}
