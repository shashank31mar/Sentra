import { useState, useCallback } from 'react'
import type { FormEvent, ChangeEvent } from 'react'

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const WEB3FORMS_ACCESS_KEY = import.meta.env.VITE_WEB3FORMS_ACCESS_KEY as string | undefined
const WEB3FORMS_ENDPOINT = 'https://api.web3forms.com/submit'

export default function DemoForm() {
  const [submitted, setSubmitted] = useState(false)
  const [sending, setSending] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [form, setForm] = useState({ name: '', email: '', company: '', useCase: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  // Honeypot — bots fill this hidden field, real users never see it
  const [botcheck, setBotcheck] = useState('')

  const isValid =
    form.name.trim() !== '' &&
    EMAIL_REGEX.test(form.email) &&
    form.company.trim() !== '' &&
    form.useCase.trim().length >= 100

  const handleChange = useCallback((e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const { name, value } = e.target
    setForm((prev) => ({ ...prev, [name]: value }))
    setErrors((prev) => ({ ...prev, [name]: '' }))
    setSubmitError('')
  }, [])

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!form.name.trim()) newErrors.name = 'Name is required'
    if (!form.email.trim()) newErrors.email = 'Email is required'
    else if (!EMAIL_REGEX.test(form.email)) newErrors.email = 'Enter a valid email address'
    if (!form.company.trim()) newErrors.company = 'Company is required'
    if (!form.useCase.trim()) newErrors.useCase = 'Use case is required'
    else if (form.useCase.trim().length < 100) newErrors.useCase = `Minimum 100 characters required (${form.useCase.trim().length}/100)`
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault()
      if (!validate()) return

      // Bot detected via honeypot — silently show success without sending
      if (botcheck) {
        setSubmitted(true)
        return
      }

      if (!WEB3FORMS_ACCESS_KEY) {
        setSubmitError('Email service is not configured. Please set VITE_WEB3FORMS_ACCESS_KEY.')
        return
      }

      setSending(true)
      setSubmitError('')

      try {
        const res = await fetch(WEB3FORMS_ENDPOINT, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({
            access_key: WEB3FORMS_ACCESS_KEY,
            subject: `Demo Request from ${form.name} — ${form.company}`,
            from_name: 'AegionAI Website',
            name: form.name,
            email: form.email,
            company: form.company,
            message: form.useCase,
            botcheck: '',
          }),
        })

        const data = await res.json()
        if (data.success) {
          setSubmitted(true)
        } else {
          setSubmitError(data.message || 'Something went wrong. Please try again.')
        }
      } catch {
        setSubmitError('Network error. Please check your connection and try again.')
      } finally {
        setSending(false)
      }
    },
    [form, botcheck]
  )

  return (
    <section id="demo" className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12">
      <div className="max-w-4xl mx-auto">
        <div className="relative p-6 sm:p-12 rounded-2xl overflow-hidden">
          {/* Gradient border */}
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-cyan via-purple to-cyan p-px">
            <div className="w-full h-full rounded-2xl bg-bg-primary" />
          </div>

          {/* Glow */}
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-32 bg-cyan/5 blur-[80px] rounded-full" />

          {/* Content */}
          <div className="relative z-10">
            <div className="text-center mb-8">
              <i className="ti ti-shield-bolt text-cyan text-4xl mb-5 block" />
              <h2 className="font-heading text-3xl font-bold text-white mb-3">Book a Demo</h2>
              <p className="font-body text-muted max-w-lg mx-auto">
                See how AegionAI governs agents across any cloud with a live cross-cloud demo.
              </p>
            </div>

            {submitted ? (
              <div className="text-center py-8">
                <i className="ti ti-circle-check text-green text-5xl mb-4 block" />
                <h3 className="font-heading text-2xl font-bold text-white mb-2">
                  Demo Requested!
                </h3>
                <p className="font-body text-muted">
                  We'll be in touch within 24 hours to schedule your live cross-cloud demo.
                </p>
              </div>
            ) : (
              <form onSubmit={handleSubmit} className="max-w-md mx-auto space-y-4">
                {/* Honeypot field — hidden from real users, catches bots */}
                <input
                  type="checkbox"
                  name="botcheck"
                  tabIndex={-1}
                  autoComplete="off"
                  checked={botcheck === 'on'}
                  onChange={(e) => setBotcheck(e.target.checked ? 'on' : '')}
                  className="hidden"
                  aria-hidden="true"
                />
                <div>
                  <label className="font-body text-xs text-muted block mb-1.5">Full Name *</label>
                  <input
                    type="text"
                    name="name"
                    value={form.name}
                    onChange={handleChange}
                    placeholder="John Doe"
                    className={`w-full px-4 py-3 rounded-lg bg-white/[0.04] border font-body text-sm text-white placeholder-muted/50 outline-none transition-colors ${errors.name ? 'border-red/60 focus:border-red/80' : 'border-white/10 focus:border-cyan/40'}`}
                  />
                  {errors.name && <p className="font-body text-xs text-red mt-1">{errors.name}</p>}
                </div>
                <div>
                  <label className="font-body text-xs text-muted block mb-1.5">Work Email *</label>
                  <input
                    type="email"
                    name="email"
                    value={form.email}
                    onChange={handleChange}
                    placeholder="john@company.com"
                    className={`w-full px-4 py-3 rounded-lg bg-white/[0.04] border font-body text-sm text-white placeholder-muted/50 outline-none transition-colors ${errors.email ? 'border-red/60 focus:border-red/80' : 'border-white/10 focus:border-cyan/40'}`}
                  />
                  {errors.email && <p className="font-body text-xs text-red mt-1">{errors.email}</p>}
                </div>
                <div>
                  <label className="font-body text-xs text-muted block mb-1.5">Company *</label>
                  <input
                    type="text"
                    name="company"
                    value={form.company}
                    onChange={handleChange}
                    placeholder="Acme Corp"
                    className={`w-full px-4 py-3 rounded-lg bg-white/[0.04] border font-body text-sm text-white placeholder-muted/50 outline-none transition-colors ${errors.company ? 'border-red/60 focus:border-red/80' : 'border-white/10 focus:border-cyan/40'}`}
                  />
                  {errors.company && <p className="font-body text-xs text-red mt-1">{errors.company}</p>}
                </div>
                <div>
                  <label className="font-body text-xs text-muted block mb-1.5">
                    Use Case * <span className="text-muted/50">(min 100 characters)</span>
                  </label>
                  <textarea
                    name="useCase"
                    rows={3}
                    value={form.useCase}
                    onChange={handleChange}
                    placeholder="Tell us about your AI agent deployment and security needs..."
                    className={`w-full px-4 py-3 rounded-lg bg-white/[0.04] border font-body text-sm text-white placeholder-muted/50 outline-none transition-colors resize-none ${errors.useCase ? 'border-red/60 focus:border-red/80' : 'border-white/10 focus:border-cyan/40'}`}
                  />
                  <div className="flex justify-between mt-1">
                    {errors.useCase ? <p className="font-body text-xs text-red">{errors.useCase}</p> : <span />}
                    <span className={`font-body text-xs ${form.useCase.trim().length >= 100 ? 'text-green' : 'text-muted/60'}`}>
                      {form.useCase.trim().length}/100
                    </span>
                  </div>
                </div>
                {submitError && (
                  <div className="flex items-center gap-2 p-3 rounded-lg bg-red/10 border border-red/20">
                    <i className="ti ti-alert-circle text-red text-base shrink-0" />
                    <p className="font-body text-xs text-red">{submitError}</p>
                  </div>
                )}
                <button
                  type="submit"
                  disabled={!isValid || sending}
                  className={`w-full mt-2 inline-flex items-center justify-center gap-2 px-8 py-4 rounded-xl font-body text-base font-semibold text-white border-none transition-all ${
                    isValid && !sending
                      ? 'bg-gradient-to-r from-cyan to-purple hover:shadow-[0_0_40px_rgba(0,240,255,0.25)] cursor-pointer'
                      : 'bg-muted/20 cursor-not-allowed opacity-50'
                  }`}
                >
                  {sending ? (
                    <>
                      Sending… <i className="ti ti-loader-2 text-lg animate-spin" />
                    </>
                  ) : (
                    <>
                      Request Demo <i className="ti ti-arrow-right text-lg" />
                    </>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
