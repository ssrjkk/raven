import { createHash } from "crypto"

export interface Embedding {
  file: string
  chunk: string
  vector: number[]
}

function hashVector(text: string, dims: number = 384): number[] {
  const hash = createHash("sha256").update(text).digest()
  const vec: number[] = []
  for (let i = 0; i < dims; i++) {
    const byte = hash[i % hash.length] ^ hash[(i * 7 + 13) % hash.length]
    vec.push((byte / 255) * 2 - 1)
  }
  return vec
}

export async function generateEmbedding(text: string): Promise<number[]> {
  const apiKey = process.env.OPENAI_API_KEY
  if (apiKey) {
    try {
      const res = await fetch("https://api.openai.com/v1/embeddings", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
        body: JSON.stringify({ input: text, model: "text-embedding-3-small" }),
      })
      const data = await res.json() as { data?: { embedding: number[] }[] }
      if (data.data?.[0]?.embedding) return data.data[0].embedding
    } catch { /* fall through */ }
  }
  return hashVector(text)
}

export async function semanticSearch(query: string, embeddings: Embedding[]): Promise<string[]> {
  if (embeddings.length === 0) return []
  const queryVec = await generateEmbedding(query)
  const scored = embeddings.map((e) => {
    const similarity = e.vector.reduce((sum, v, i) => sum + v * queryVec[i], 0)
    return { file: e.file, similarity }
  })
  scored.sort((a, b) => b.similarity - a.similarity)
  return scored.slice(0, 5).map((e) => e.file)
}
