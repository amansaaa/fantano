/**
 * what shows for the split second while an artist page's queries run: gray blocks in the same
 * layout as the real page, so nothing jumps around when it arrives. next.js shows this
 * automatically (it wraps page.tsx in a react Suspense boundary).
 */

// same counts as the real page: a 12-card grid and a few track rows
const GRID_CARDS = 12;
const TRACK_ROWS = 3;

export default function ArtistLoading() {
  return (
    <div aria-busy="true" aria-label="Loading artist" className="mx-auto max-w-6xl animate-pulse px-4 pb-24 motion-reduce:animate-none md:px-8">
      <header className="flex items-center justify-between gap-6 py-6">
        <div className="h-4 w-14 rounded bg-placeholder" />
        <div className="h-11 w-full max-w-sm rounded-full bg-placeholder" />
      </header>

      <div className="mt-4 grid gap-12 lg:grid-cols-[20rem_1fr] lg:gap-14">
        <div className="flex flex-col gap-6">
          <div className="aspect-square w-full max-w-80 rounded-2xl bg-placeholder" />
          <div className="h-8 w-48 rounded bg-placeholder" />
          <div className="h-52 rounded-2xl bg-placeholder" />
        </div>

        <div className="flex flex-col gap-14">
          <div>
            <div className="mb-5 h-3 w-64 rounded bg-placeholder" />
            <div className="grid grid-cols-3 gap-x-4 gap-y-6 sm:grid-cols-4 lg:grid-cols-6">
              {Array.from({ length: GRID_CARDS }, (_, index) => (
                <div key={index}>
                  <div className="aspect-square rounded-md bg-placeholder" />
                  <div className="mt-2 h-3 w-3/4 rounded bg-placeholder" />
                </div>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-5 h-3 w-56 rounded bg-placeholder" />
            {Array.from({ length: TRACK_ROWS }, (_, index) => (
              <div key={index} className="grid grid-cols-[1.75rem_4rem_1fr] gap-x-4 py-6">
                <div />
                <div className="size-16 rounded-md bg-placeholder" />
                <div className="flex flex-col gap-2">
                  <div className="h-4 w-1/3 rounded bg-placeholder" />
                  <div className="h-3 w-full rounded bg-placeholder" />
                  <div className="h-3 w-2/3 rounded bg-placeholder" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
