You are extracting facts from the transcript of an Anthony Fantano (theneedledrop) album review or track review.

# Input

You get the video title and the transcript. Each transcript line looks like this:

    [44 @ 3:10] which honestly gives me some frank ocean

`44` is the line number and `3:10` is when it's said. The transcript comes from YouTube auto-captions, so artist names are often misheard (for example "Ay Chike" for "AZ Chike").

# Output

Return JSON only, in the given schema. Every quote must be copied from the transcript, word for word. Never write a quote in your own words. Every `line` must be a line number that appears in the transcript.

## liked
`true` if his overall verdict is positive, `false` if it's mixed or negative.

## summary
2–3 sentences, in your own words, on his overall verdict: what he liked, what he didn't, and why. Write it in the third person ("He finds the production..."). Don't repeat the score.

## pull_quote
The one sentence of his that best sums up his opinion. `line` is where it starts.

## connections
Every time he relates the reviewed artist (or their music) to another musical artist. One entry per mention.

- `artist`: the other artist, correctly spelled if you recognize them.
- `heard_as`: the name exactly as it appears in the transcript, misspellings included.
- `about_artist`: the artist being discussed when he made the link, usually the reviewed artist.
- `label`: exactly one of:
  - `sounds_like`: the music resembles the other artist ("gives me Frank Ocean vibes", "very Radiohead").
  - `influenced_by`: the artist draws on, was shaped by, or pays tribute to the other artist.
  - `contrast`: he compares them to say they're different, or that the other artist does it better or worse ("unlike Drake, he actually has bars").
  - `collaborator`: the other artist actually worked on the music (a feature, a producer, a co-writer).
- `line`: the line where the other artist's name is spoken.
- `quote`: his words around that name, 1–2 sentences, starting no more than 2 lines before `line`.

Skip mentions that aren't musical comparisons: news, gossip, his own opinions of a person, or other videos he's plugging ("I saw Frank Ocean memes all week", "check out my Drake review").

## track_takes
Songs from this release that he talks about individually. At most 8, prioritizing the ones he says the most about.

- `track`: the song title as he says it.
- `line`: where his comment on the song starts.
- `quote`: his words about the song, 1–2 sentences.
- `summary`: 1–2 sentences, in your own words, on what he thinks of it.
