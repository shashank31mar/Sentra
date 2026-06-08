export default function Contact() {
  return (
    <section id="contact" className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12 border-t border-white/5">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-12 sm:mb-16">
          <span className="font-body text-sm font-medium tracking-widest uppercase text-cyan">
            Contact
          </span>
          <h2 className="font-heading text-3xl sm:text-4xl font-bold text-white mt-4 mb-4">Get in Touch</h2>
          <p className="font-body text-muted max-w-xl mx-auto">
            Have questions about AegionAI? Want to discuss your AI security challenges? Reach out —
            we'd love to hear from you.
          </p>
        </div>

        <div className="max-w-md mx-auto">
          <a
            href="mailto:info@aegionai.ai"
            className="block p-8 rounded-2xl bg-white/[0.02] border border-white/5 text-center hover:border-cyan/20 transition-colors group"
          >
            <div className="w-14 h-14 rounded-2xl bg-cyan/10 border border-cyan/20 flex items-center justify-center mx-auto mb-5">
              <i className="ti ti-mail text-cyan text-2xl" />
            </div>
            <h3 className="font-heading text-base font-semibold text-white mb-2">Email Us</h3>
            <span className="font-body text-sm text-muted group-hover:text-cyan transition-colors">
              info@aegionai.ai
            </span>
          </a>
        </div>
      </div>
    </section>
  )
}
