/** Remember each successful save so generating a plan or retrying cannot resave it. */
export async function persistTasks<T extends { id: string }>(
  drafts: T[],
  persisted: Map<string, T>,
  create: (draft: T) => Promise<T>,
): Promise<T[]> {
  const result: T[] = [];
  for (const draft of drafts) {
    let saved = persisted.get(draft.id);
    if (!saved) {
      saved = await create(draft);
      persisted.set(draft.id, saved);
      persisted.set(saved.id, saved);
    }
    result.push(saved);
  }
  return result;
}
