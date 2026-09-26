/**
 * the small muted blue caps heading above each section ("SIMILAR ARTISTS ACCORDING TO FANTANO").
 *
 * usage:
 *   <SectionLabel>12 Tracks Fantano recommends</SectionLabel>
 */

export default function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-5 text-xs font-medium tracking-[0.16em] text-label uppercase">{children}</h2>;
}
