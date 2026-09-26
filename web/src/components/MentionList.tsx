/**
 * "Every time Fantano mentioned X", for artists he never reviewed. one row per spoken mention:
 * who he was talking about, how he related them, his words, and ▶ Watch.
 *
 * usage:
 *   <MentionList mentions={mentions} artistName="Björk" />
 */

import Link from "next/link";

import SectionLabel from "@/components/SectionLabel";
import WatchLink from "@/components/WatchLink";
import { LABEL_TEXT } from "@/lib/labels";
import type { Mention } from "@/lib/types";

type Props = {
  mentions: Mention[];
  artistName: string;
};

export default function MentionList({ mentions, artistName }: Props) {
  return (
    <section>
      <SectionLabel>Every time Fantano mentioned {artistName}</SectionLabel>

      {mentions.length === 0 && (
        <p className="text-sm text-muted">He hasn’t said {artistName}’s name out loud yet, only listed them as a featured artist.</p>
      )}

      <ol>
        {mentions.map((mention) => (
          <li key={`${mention.video_id}-${mention.start_s}-${mention.other_id}`} className="border-t border-line py-5 first:border-t-0 first:pt-0">
            <p className="text-sm text-muted">
              {LABEL_TEXT[mention.label]} ·{" "}
              <Link href={`/artist/${mention.other_id}`} className="font-medium text-ink hover:underline">
                {mention.other_name}
              </Link>
            </p>
            {mention.quote && <p className="mt-2 text-[15px] leading-relaxed text-ink">“{mention.quote}”</p>}
            <div className="mt-2">
              <WatchLink videoId={mention.video_id} startSeconds={mention.start_s} videoTitle={mention.video_title} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
