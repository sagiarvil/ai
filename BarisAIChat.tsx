// ==============================================================================
// DOSYA: BarisAIChat.tsx (Next.js / React Modern Kokpit Arayüzü)
// ==============================================================================
import React, { useState, useRef, useEffect, ChangeEvent } from "react";
import { Paperclip, Square, Send, FileText, CheckCircle2, AlertCircle } from "lucide-react";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
}

interface Attachment {
  filename: string;
  extracted_text: string;
}

export default function BarisAIChat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  const MAX_CHARS = 5000;

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("http://127.0.0.1:5050/api/upload", {
          method: "POST",
          body: formData,
        });
        if (res.ok) {
          const data = await res.json();
          setAttachments((prev) => [
            ...prev,
            { filename: data.filename, extracted_text: data.extracted_text },
          ]);
        }
      } catch (err) {
        console.error("Yükleme hatası:", err);
      }
    }
    e.target.value = "";
  };

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setIsLoading(false);
    }
  };

  const handleSend = async () => {
    const trimmedInput = input.trim();
    if ((!trimmedInput && attachments.length === 0) || isLoading) return;

    let promptWithAttachments = trimmedInput;
    if (attachments.length > 0) {
      const docsSummary = attachments
        .map(
          (a) =>
            `📎 [EKLENEN BELGE: ${a.filename}]\n${a.extracted_text.slice(0, 4000)}`
        )
        .join("\n\n");
      promptWithAttachments = `${docsSummary}\n\n${trimmedInput}`;
    }

    const newUserMessage: Message = { role: "user", content: promptWithAttachments };
    const updatedMessages = [...messages, newUserMessage];
    setMessages(updatedMessages);
    setInput("");
    setAttachments([]);
    setIsLoading(true);

    abortControllerRef.current = new AbortController();

    try {
      // 10 turluk kayan hafıza penceresi (son 20 mesaj)
      const slidingWindow = updatedMessages.slice(-20);

      const res = await fetch("http://127.0.0.1:5050/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: promptWithAttachments,
          history: slidingWindow,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!res.ok) {
        throw new Error(`HTTP Hata: ${res.status}`);
      }

      const data = await res.json();
      const assistantReply = data.reply || "İşlem tamamlandı.";

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: assistantReply },
      ]);
    } catch (err: any) {
      if (err.name === "AbortError") {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: "⏹ *İşlem kullanıcı tarafından durduruldu.*" },
        ]);
      } else {
        setMessages((prev) => [
          ...prev,
          { role: "assistant", content: `⚠️ Hata oluştu: ${err.message}` },
        ]);
      }
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-5xl mx-auto bg-slate-900 text-slate-100 font-sans border-x border-slate-800">
      {/* Üst Bar */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/70 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
          <h1 className="text-lg font-bold tracking-tight text-white">
            Baris AI <span className="text-xs px-2 py-0.5 ml-2 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">Mühendislik Çekirdeği</span>
          </h1>
        </div>
        <div className="text-xs text-slate-400">
          Hafıza: <span className="text-emerald-400 font-mono">10 Tur Kayan Pencere</span> | Giriş: <span className="text-indigo-400 font-mono">5.000 Karakter</span>
        </div>
      </header>

      {/* Mesaj Akışı */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 space-y-2">
            <CheckCircle2 className="w-10 h-10 text-slate-600" />
            <p className="text-sm">Baris AI hazır. Komutunuzu, dosyanızı veya teknik görevinizi iletin.</p>
          </div>
        )}

        {messages.map((m, idx) => (
          <div
            key={idx}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-5 py-3.5 text-sm leading-relaxed whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-indigo-600 text-white rounded-br-none shadow-lg shadow-indigo-600/10"
                  : "bg-slate-800/90 text-slate-200 border border-slate-700/60 rounded-bl-none shadow"
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-slate-800/90 border border-slate-700/60 rounded-2xl rounded-bl-none px-5 py-3.5 flex items-center gap-3 text-sm text-slate-300">
              <span className="w-2 h-2 rounded-full bg-indigo-400 animate-ping" />
              <span>İcra ediliyor ve doğrulanıyor...</span>
            </div>
          </div>
        )}
        <div ref={chatBottomRef} />
      </div>

      {/* Eklenen Belgeler Tepsisi */}
      {attachments.length > 0 && (
        <div className="px-6 py-2 bg-slate-950/50 border-t border-slate-800/50 flex flex-wrap gap-2">
          {attachments.map((a, i) => (
            <div
              key={i}
              className="flex items-center gap-2 bg-slate-800 border border-slate-700 px-3 py-1 rounded-full text-xs text-slate-300"
            >
              <FileText className="w-3.5 h-3.5 text-indigo-400" />
              <span className="max-w-[150px] truncate">{a.filename}</span>
              <button
                type="button"
                onClick={() => setAttachments(attachments.filter((_, idx) => idx !== i))}
                className="text-slate-400 hover:text-red-400 ml-1"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Giriş & Kontrol Alanı */}
      <div className="p-4 bg-slate-950/80 border-t border-slate-800">
        <div className="relative bg-slate-900 border border-slate-800 rounded-xl focus-within:border-indigo-500/60 transition-colors shadow-inner">
          <textarea
            value={input}
            onChange={(e) => {
              if (e.target.value.length <= MAX_CHARS) {
                setInput(e.target.value);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Baris AI'ye teknik talimatınızı iletin (Enter ile gönder, Shift+Enter ile alt satır)..."
            rows={3}
            className="w-full bg-transparent p-3.5 text-sm text-slate-100 placeholder-slate-500 resize-none outline-none"
          />

          <div className="flex items-center justify-between px-3.5 py-2 border-t border-slate-800/40 bg-slate-900/50 rounded-b-xl">
            {/* Sol Araçlar */}
            <div className="flex items-center gap-3">
              <label className="cursor-pointer text-slate-400 hover:text-indigo-400 transition-colors flex items-center gap-1.5 text-xs">
                <Paperclip className="w-4 h-4" />
                <span>Dosya Ekle</span>
                <input
                  type="file"
                  multiple
                  onChange={handleFileUpload}
                  className="hidden"
                  accept=".pdf,.doc,.docx,.png,.jpg,.jpeg,.py,.md,.txt,.json,.ts,.tsx"
                />
              </label>

              {/* Dinamik Karakter Sayacı */}
              <span
                className={`text-xs font-mono transition-colors ${
                  input.length >= 4500
                    ? input.length >= MAX_CHARS
                      ? "text-red-400 font-bold"
                      : "text-amber-400"
                    : "text-slate-500"
                }`}
              >
                {input.length} / {MAX_CHARS}
              </span>
            </div>

            {/* Sağ Eylemler: Durdur & Gönder */}
            <div className="flex items-center gap-2">
              {isLoading && (
                <button
                  type="button"
                  onClick={handleStop}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-600/20 text-red-400 border border-red-500/30 hover:bg-red-600/30 text-xs font-medium transition-colors"
                >
                  <Square className="w-3.5 h-3.5 fill-current" />
                  <span>Durdur</span>
                </button>
              )}

              <button
                type="button"
                onClick={handleSend}
                disabled={isLoading || (!input.trim() && attachments.length === 0)}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-medium transition-colors shadow-sm"
              >
                <Send className="w-3.5 h-3.5" />
                <span>Gönder</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
