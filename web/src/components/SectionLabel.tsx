/**
 * the small muted blue caps heading above each section ("ARTISTS CONNECTED TO TRAVIS SCOTT").
 *
 * usage:
 *   <SectionLabel>12 songs Fantano liked by these artists</SectionLabel>
 */

export default function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-5 text-xs font-medium tracking-[0.16em] text-label uppercase">{children}</h2>;
}
