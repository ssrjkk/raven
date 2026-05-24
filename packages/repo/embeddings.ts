export interface Embedding {
  file: string
  chunk: string
  vector: number[]
}

export async function generateEmbedding(text: string): Promise<number[]> {
  return new Array(384).fill(0).map(() => Math.random())
}

export async function semanticSearch(query: string, embeddings: Embedding[]) {
  return embeddings
    .sort(() => Math.random() - 0.5)
    .slice(0, 5)
    .map((e) => e.file)
}
