// ==============================================================================
// DOSYA: BarisAIChat.tsx (Next.js / React Endüstriyel Ajan Kokpiti)
// ==============================================================================
import React, { useState, useRef, useEffect } from "react";
import { Send, Square, Paperclip, FileText, Trash2 } from "lucide-react";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

export default function BarisAIChat() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; text: string }[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  const MAX_CHARS = 5000;
  const remainingChars = MAX_CHARS - input.length;

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // SOHBETİ VE SAYFAYI TEMİZLE
  const handleClear = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setMessages([]);
    setAttachedFiles([]);
    setInput("");
  };

  // DOSYA YÜKLEME YÖNETİMİ (PDF, Word, Görsel)
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const file = e.target.files[0];
    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://127.0.0.1:5050/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      setAttachedFiles((prev) => [...prev, { name: data.filename, text: data.extracted_text }]);
    } catch {
      alert("Dosya yüklenemedi. Backend servisinin açık olduğunu kontrol edin.");
    }
  };

  // TALİMAT İLETİMİ VE 10 DİYALOGLUK SLIDING WINDOW BAĞLAM YÖNETİMİ
  const handleSend = async () => {
    if ((!input.trim() && attachedFiles.length === 0) || isLoading) return;

    let fullPrompt = input;
    if (attachedFiles.length > 0) {
      const fileContext = attachedFiles
        .map((f) => `--- DOSYA: ${f.name} ---\n${f.text}\n---`)
        .join("\n\n");
      fullPrompt = `${fileContext}\n\nKULLANICI TALİMATI:\n${input}`;
    }

    const newMessages: Message[] = [...messages, { role: "user", content: fullPrompt }];
    setMessages(newMessages);
    setInput("");
    setAttachedFiles([]);
    setIsLoading(true);

    // ABORT CONTROLLER (STOP BUTONU ALTYAPISI)
    abortControllerRef.current = new AbortController();

    // SON 10 DİYALOG TURUNU (20 MESAJ) KİLİTLE - BAĞLAM KAYBI ÖNLENİR
    const slidingContext = newMessages.slice(-20);

    try {
      // Yerel LLM / Agent API çağrısı
      const response = await fetch("http://127.0.0.1:5050/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: slidingContext }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.body) throw new Error("Akış algılanamadı");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let assistantMsg = "";

      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        assistantMsg += decoder.decode(value, { stream: true });

        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1].content = assistantMsg;
          return updated;
        });
      }
    } catch (err: any) {
      if (err.name === "AbortError") {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "[İşlem kullanıcı tarafından durduruldu.]" },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "Sunucu bağlantı hatası oluştu." },
        ]);
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-5xl mx-auto bg-neutral-950 text-neutral-100 font-sans border-x border-neutral-800">
      {/* ÜST BİLGİ PANELİ */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800 bg-neutral-900/50 backdrop-blur">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
          <h1 className="font-semibold text-lg tracking-tight">Baris AI // Endüstriyel Ajan Kokpiti</h1>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-xs text-neutral-400">Context: Son 10 Tur Aktif | Bellek: Kayan Pencere</div>
          <button
            onClick={handleClear}
            className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-neutral-300 hover:text-rose-400 hover:bg-rose-950/30 border border-neutral-700 hover:border-rose-800/60 rounded-lg transition"
            title="Sohbet geçmişini ve sayfayı temizle"
          >
            <Trash2 size={13} />
            <span>Temizle</span>
          </button>
        </div>
      </div>

      {/* DİYALOG AKIŞ ALANI */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] p-4 rounded-xl text-sm leading-relaxed whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-blue-600/20 border border-blue-500/30 text-blue-100"
                  : "bg-neutral-900 border border-neutral-800 text-neutral-200"
              }`}
            >
              <div className="text-[10px] uppercase tracking-wider mb-1 opacity-50 font-bold">
                {m.role === "user" ? "MÜHENDİS (SEN)" : "BARIS AI"}
              </div>
              {m.content}
            </div>
          </div>
        ))}
        <div ref={chatBottomRef} />
      </div>

      {/* GİRİŞ VE KONTROL PANELİ */}
      <div className="p-4 border-t border-neutral-800 bg-neutral-900/60">
        {/* Eklenen Dosyalar */}
        {attachedFiles.length > 0 && (
          <div className="flex gap-2 mb-2 flex-wrap">
            {attachedFiles.map((f, i) => (
              <span
                key={i}
                className="flex items-center gap-1 text-xs bg-neutral-800 border border-neutral-700 px-2 py-1 rounded text-neutral-300"
              >
                <FileText size={12} /> {f.name}
              </span>
            ))}
          </div>
        )}

        <div className="relative rounded-xl border border-neutral-700 bg-neutral-950 p-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_CHARS))}
            placeholder="Talimatı girin... (Dosya üretme, kodlama, mimari analiz, Git commit)"
            className="w-full bg-transparent resize-none outline-none text-sm p-2 h-24 placeholder:text-neutral-500"
          />

          <div className="flex items-center justify-between border-t border-neutral-800/80 pt-2 px-1">
            <div className="flex items-center gap-3">
              {/* Dosya Ekleme Butonu */}
              <label className="cursor-pointer text-neutral-400 hover:text-neutral-200 transition">
                <Paperclip size={18} />
                <input
                  type="file"
                  multiple
                  onChange={handleFileUpload}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.txt,.py,.md,.png,.jpg"
                />
              </label>

              {/* Dinamik Karakter Sayacı */}
              <span
                className={`text-xs font-mono ${
                  remainingChars < 200 ? "text-amber-500" : "text-neutral-500"
                }`}
              >
                {input.length} / {MAX_CHARS}
              </span>
            </div>

            {/* Çalıştırma & Durdurma (Stop) Butonları */}
            <div className="flex items-center gap-2">
              {isLoading ? (
                <button
                  onClick={handleStop}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600/20 border border-rose-500/40 text-rose-400 text-xs font-medium hover:bg-rose-600/30 transition"
                >
                  <Square size={13} fill="currentColor" /> Durdur
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!input.trim() && attachedFiles.length === 0}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium disabled:opacity-40 transition"
                >
                  <Send size={13} /> Gönder
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
