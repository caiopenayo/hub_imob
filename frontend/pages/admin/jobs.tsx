import { useEffect, useState } from 'react'
import Head from 'next/head'

import { AppShell } from '../../components/AppShell'

type Job = {
  id: string
  job_name: string
  source_ids?: string[]
  mode: string
  status: string
  started_at?: string
  finished_at?: string
  summary?: Record<string, unknown>
  error?: string
  created_at: string
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function formatDate(value?: string): string {
  if (!value) return '-'
  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(new Date(value))
}

function statusClass(status: string): string {
  if (status === 'success') return 'status success'
  if (status === 'failed') return 'status failed'
  if (status === 'running') return 'status running'
  return 'status'
}

function statusLabel(status: string): string {
  if (status === 'success') return 'Concluída'
  if (status === 'failed') return 'Falhou'
  if (status === 'running') return 'Em andamento'
  return status
}

export default function JobsAdmin() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(20)
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<Job | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void fetchJobs()
  }, [page])

  async function fetchJobs() {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/scrape/jobs?page=${page}&per_page=${perPage}`)
      if (!res.ok) throw new Error(`Erro: ${res.status}`)
      const data = await res.json()
      const nextJobs = data.items ?? []
      setJobs(nextJobs)
      setTotal(data.meta?.total ?? 0)
      if (!selected && nextJobs.length > 0) {
        setSelected(nextJobs[0])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }

  async function loadJobDetail(id: string) {
    try {
      const res = await fetch(`${API_URL}/scrape/jobs/${id}`)
      if (!res.ok) throw new Error(`Erro: ${res.status}`)
      const data = await res.json()
      setSelected(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro desconhecido')
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / perPage))
  const successCount = jobs.filter((job) => job.status === 'success').length
  const failedCount = jobs.filter((job) => job.status === 'failed').length
  const runningCount = jobs.filter((job) => job.status === 'running').length

  return (
    <AppShell>
      <Head>
        <title>Imob Hub | Rotinas</title>
      </Head>

      <main className="page admin-page">
        <section className="admin-header">
          <div>
            <p className="eyebrow">Operações</p>
            <h1>Rotinas de coleta</h1>
            <p>Acompanhe execuções, falhas de ingestão e volume coletado pelas fontes.</p>
          </div>
          <button className="button button-secondary" type="button" onClick={() => void fetchJobs()} disabled={loading}>
            Atualizar
          </button>
        </section>

        <section className="stats-grid" aria-label="Resumo das rotinas">
          <div className="stat">
            <span>Total</span>
            <strong>{total}</strong>
          </div>
          <div className="stat">
            <span>Rodando</span>
            <strong>{runningCount}</strong>
          </div>
          <div className="stat">
            <span>Sucesso</span>
            <strong>{successCount}</strong>
          </div>
          <div className="stat">
            <span>Falhas</span>
            <strong>{failedCount}</strong>
          </div>
        </section>

        {error && <div className="notice notice-error">{error}</div>}

        <section className="admin-layout">
          <div className="table-shell">
            <div className="table-title">
              <h2>Execuções recentes</h2>
              <span>{loading ? 'Carregando...' : `${jobs.length} nesta página`}</span>
            </div>

            <div className="table-scroll">
              <table className="jobs-table">
                <thead>
                  <tr>
                    <th>Rotina</th>
                    <th>Status</th>
                    <th>Modo</th>
                    <th>Início</th>
                    <th>Fim</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job) => (
                    <tr key={job.id}>
                      <td>
                        <button className="job-link" type="button" onClick={() => void loadJobDetail(job.id)}>
                          {job.id.slice(0, 8)}
                        </button>
                      </td>
                      <td>
                        <span className={statusClass(job.status)}>{statusLabel(job.status)}</span>
                      </td>
                      <td>{job.mode}</td>
                      <td>{formatDate(job.started_at)}</td>
                      <td>{formatDate(job.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!loading && jobs.length === 0 ? (
              <div className="empty-inline">Nenhuma rotina registrada ainda.</div>
            ) : null}

            <div className="pagination compact" aria-label="Paginação de rotinas">
              <button className="button button-secondary" type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
                Anterior
              </button>
              <span>{page} / {totalPages}</span>
              <button className="button button-secondary" type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
                Próxima
              </button>
            </div>
          </div>

          <aside className="detail-panel">
            <p className="eyebrow">Detalhes</p>
            {!selected ? (
              <p className="muted">Selecione uma rotina para ver detalhes.</p>
            ) : (
              <>
                <h2>{selected.id.slice(0, 8)}</h2>
                <dl className="detail-list">
                  <div>
                    <dt>Status</dt>
                    <dd><span className={statusClass(selected.status)}>{statusLabel(selected.status)}</span></dd>
                  </div>
                  <div>
                    <dt>Modo</dt>
                    <dd>{selected.mode}</dd>
                  </div>
                  <div>
                    <dt>Fontes</dt>
                    <dd>{selected.source_ids?.join(', ') || 'Todas'}</dd>
                  </div>
                  <div>
                    <dt>Criado</dt>
                    <dd>{formatDate(selected.created_at)}</dd>
                  </div>
                  <div>
                    <dt>Início</dt>
                    <dd>{formatDate(selected.started_at)}</dd>
                  </div>
                  <div>
                    <dt>Fim</dt>
                    <dd>{formatDate(selected.finished_at)}</dd>
                  </div>
                </dl>

                <h3>Resumo</h3>
                <pre className="code-block">{JSON.stringify(selected.summary ?? {}, null, 2)}</pre>

                {selected.error ? (
                  <>
                    <h3>Erro</h3>
                    <pre className="code-block error-block">{selected.error}</pre>
                  </>
                ) : null}
              </>
            )}
          </aside>
        </section>
      </main>
    </AppShell>
  )
}
