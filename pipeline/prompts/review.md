You are extracting facts from the transcript of an Anthony Fantano (theneedledrop) album review or track review.

# Input

You get the video title, his FAV TRACKS list (when he wrote one), and the transcript. Each transcript line looks like this:

    [44 @ 3:10] and the production on this track is

`44` is the line number and `3:10` is when it's said. The transcript comes from YouTube auto-captions, so artist names are often misheard.

# Output

Return JSON only, in the given schema. Every quote must be copied from the transcript, word for word. Never write a quote in your own words. A quote is one continuous passage: never join separate parts with "...". Every `line` must be a line number that appears in the transcript.

## liked
`true` if his overall verdict is positive, `false` if it's mixed or negative.

## summary
2–3 sentences, in your own words, on his overall verdict: what he liked, what he didn't, and why. Write it in the third person ("He finds the production..."). Don't repeat the score.

## pull_quote
The one sentence of his that best sums up his opinion. `line` is the line where the quote starts.

## connections
Every time he relates the reviewed artist (or their music) to another musical artist. One entry per mention.

- `artist`: the other artist, correctly spelled if you recognize them.
- `heard_as`: the name exactly as it appears in the transcript, misspellings included.
- `about_artist`: the artist being discussed when he made the link, usually the reviewed artist.
- `label`: exactly one of:
  - `sounds_like`: the music resembles the other artist ("gives me [artist] vibes", "very [artist]").
  - `influenced_by`: the artist draws on, was shaped by, or pays tribute to the other artist.
  - `contrast`: he compares them to say they're different, or that the other artist does it better or worse ("unlike [artist], he actually has bars").
  - `collaborator`: the other artist actually worked on the music (a feature, a producer, a co-writer).
- `line`: the line where the other artist's name is spoken.
- `quote`: his words around that name, 1–2 sentences, starting no more than 2 lines before `line`.

Every featured artist he names on this release ("with [artist]", "featuring [artist]") is a `collaborator` connection, with `about_artist` = the reviewed artist. A band membership ("[person] of [band]") is not a connection; the connection is to the featured person.

Skip mentions that aren't musical comparisons: news, gossip, his opinion of someone as a person, or plugs for his other videos.

## track_takes
Every song from this release that he comments on individually, up to 12. Include every song from FAV TRACKS that he talks about in the transcript, even briefly: those are the songs we recommend. For a track review, leave `track_takes` empty.

- `track`: the song title as he says it.
- `line`: the line where the quote starts.
- `quote`: his words about the song, 1–2 sentences.
- `summary`: 1–2 sentences, in your own words, on what he thinks of it.

The examples above use [artist] as a placeholder. Only report artists whose names actually appear in this transcript.
