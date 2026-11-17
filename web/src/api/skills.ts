import client from './client'

interface Wrapped<T> {
  code: number
  message: string
  data: T
}

export interface FewShot {
  input: string
  output: string
}

export interface SkillConfig {
  quick_prompts?: string[]
  few_shots?: FewShot[]
}

export interface Skill {
  id: string
  name: string
  description: string
  icon: string
  prompt: string
  tool_keys: string[]
  kb_id: string | null
  enabled: boolean
  config: SkillConfig
  is_builtin: boolean
  package?: { id: string; activeVersion: string; versions: { version: string; source: string; commit?: string; tools: string[] }[] } | null
}

export interface PackagePreview {
  manifest: { name: string; version: string; tools: string[] }
  digest: string
  references: string[]
  unavailable: string[]
  prompt: string
  previousVersion?: string
  previousPrompt?: string
  localPromptEdited?: boolean
}

export interface SkillInput {
  name: string
  description?: string
  icon?: string
  prompt?: string
  tool_keys?: string[]
  kb_id?: string | null
  enabled?: boolean
  config?: SkillConfig
}

export interface BuiltinSkill {
  key: string
  name: string
  description: string
  icon: string
  prompt: string
  tool_keys: string[]
  config: SkillConfig
}

export const skillApi = {
  previewPackage: (body: FormData) => client.post<unknown, Wrapped<PackagePreview>>('/skills/packages/preview', body),
  installPackage: (body: FormData) => client.post<unknown, Wrapped<Skill>>('/skills/packages/install', body),
  rollback: (id: string, version: string) => client.post<unknown, Wrapped<Skill>>(`/skills/${id}/packages/rollback`, { version }),
  list(signal?: AbortSignal) {
    return client.get<unknown, Wrapped<Skill[]>>('/skills', { signal })
  },
  builtins() {
    return client.get<unknown, Wrapped<BuiltinSkill[]>>('/skills/builtins')
  },
  create(body: SkillInput) {
    return client.post<unknown, Wrapped<Skill>>('/skills', body)
  },
  addBuiltin(key: string) {
    return client.post<unknown, Wrapped<Skill>>(`/skills/builtins/${key}`, {})
  },
  optimizePrompt(prompt: string) {
    return client.post<unknown, Wrapped<{ optimized: string }>>(
      '/skills/optimize-prompt',
      { prompt },
    )
  },
  update(id: string, body: Partial<SkillInput>) {
    return client.put<unknown, Wrapped<Skill>>(`/skills/${id}`, body)
  },
  remove(id: string) {
    return client.delete<unknown, Wrapped<null>>(`/skills/${id}`)
  },
}
