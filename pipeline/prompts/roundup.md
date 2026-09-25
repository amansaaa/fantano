You are extracting facts from the transcript of an Anthony Fantano (theneedledrop) Weekly Track Roundup, a video where he goes through many new songs by different artists.

# Input

You get the video title, a numbered TRACKS list, and the transcript.

The TRACKS list comes from the video description, so the artist names and song titles in it are spelled correctly. Each entry shows the list it's on (best, meh, or worst):

    3. [best] [artist] - [song] (ft. [artist])

Each transcript line looks like this:

    [44 @ 3:10] and the production on this track is

`44` is the line number and `3:10` is when it's said. The transcript comes from YouTube auto-captions, so names are often misheard.

# Output

Return JSON only, in the given schema. Every quote must be copied from the transcript, word for word. Never write a quote in your own words. A quote is one continuous passage: never join separate parts with "...". Every `line` must be a line number that appears in the transcript.

## track_takes
One entry for each track from the TRACKS list that he talks about. Skip tracks he doesn't discuss.

- `track`: the track's number in the TRACKS list.
- `line`: the line where the quote starts.
- `quote`: his words about the track, 1–2 sentences.
- `summary`: 1–2 sentences, in your own words, on what he thinks of it.

## connections
Every time he relates a track (or its artist) to a different musical artist. One entry per mention.

- `track`: the number of the track he was discussing when he made the link.
- `artist`: the other artist, correctly spelled if you recognize them.
- `heard_as`: the name exactly as it appears in the transcript, misspellings included.
- `label`: exactly one of:
  - `sounds_like`: the music resembles the other artist ("gives me [artist] vibes", "very [artist]").
  - `influenced_by`: the artist draws on, was shaped by, or pays tribute to the other artist.
  - `contrast`: he compares them to say they're different, or that the other artist does it better or worse ("unlike [artist], this actually has a hook").
  - `collaborator`: the other artist worked on the track (a producer or co-writer he names).
- `line`: the line where the other artist's name is spoken.
- `quote`: his words around that name, 1–2 sentences.

Don't report the artists already in the TRACKS list for that same track (the track's own artist and its "ft." artists); those are known from the list. Skip mentions that aren't musical comparisons: news, gossip, his opinion of someone as a person, or plugs for his other videos.

The examples above use [artist] and [song] as placeholders. Only report artists whose names actually appear in this transcript.
