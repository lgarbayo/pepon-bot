# Pepón

Robot de escritorio: el móvil aporta cámara, micrófono, pantalla, altavoz y sensores; el PC ejecuta FastAPI, YOLO, Whisper y Gemma mediante Ollama.

## Arranque

```sh
# En una terminal, si Ollama no está ya activo:
ollama serve

# En otra terminal:
cd /home/lgarbayo/pepon-bot/server
python3 main.py
```

Abre `https://<IP-LAN>:8000` en el móvil y acepta el certificado local. `/debug` muestra cámara, memoria, voz, encargos y avisos. La primera pulsación desbloquea el audio del navegador.

## Conversación y controles

- Toca la esfera para conversar. El micro se mantiene abierto durante esa sesión; termina cada frase tras aproximadamente **700 ms de silencio**, sin pulsar para enviarla. Conserva hasta 420 ms previos a la detección del inicio. Las frases se limitan a 20 segundos para acotar memoria y peticiones.
- Las barras reflejan el volumen real del micro. La esfera distingue escucha, procesamiento, respuesta y error. Las respuestas también aparecen escritas.
- Puedes interrumpir una respuesta hablando. La captura pide cancelación de eco y exige voz sostenida más intensa mientras suena Pepón. Es una detección energética adaptativa: ruido fuerte o eco residual pueden confundirse con voz; requiere ajustar/verificar en el Redmi real.
- Toca de nuevo para terminar: cierra las pistas del micro y el AudioContext, cancela la petición y el habla, y descarta las respuestas tardías. También lo hace al ocultar la página o perder el WebSocket.
- En el menú **PEPÓN** puedes activar el modo tranquilo, ver encargos y cancelarlos. El modo tranquilo desactiva los comentarios espontáneos; conserva las respuestas y avisos solicitados.

La captura utiliza [AudioWorklet](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorkletProcessor), procesado local y WAV mono. Whisper sigue siendo el único transcriptor; no se envía audio a un servicio externo. Las animaciones de habla representan el estado de reproducción: el navegador no expone el audio de `speechSynthesis` al medidor del micro.

## Ejemplos

| Función | Qué puedes decir |
| --- | --- |
| Percepción | «¿Qué ves?», «¿Ves una botella?», «Busca el libro», «Mírame» |
| Referencias entre turnos | «¿Ves una botella?» → «¿Dónde está?» → «Avísame cuando desaparezca» |
| Memoria visual | «¿Dónde viste mi taza por última vez?» |
| Cambios | «¿Qué ha cambiado en la mesa?» |
| Avisos | «Avísame cuando aparezca alguien», «Vigila si vuelve a estar la taza» |
| Recordatorios de regreso | «Recuérdame beber agua cuando vuelva» |
| Gestión | «Qué encargos tienes», «Cancela los avisos de la taza», «Cancela todos los encargos» |
| Personalidad | «Modo tranquilo», «Modo sociable» |

El parser cubre las **80 clases COCO**, sus nombres españoles y sinónimos. Gemma recibe hasta 12 turnos recientes y el estado visual actual para otras preguntas. El referente caduca tras cinco minutos de inactividad y se reinicia al comenzar otra sesión.

## Memoria, avisos y personalidad

- La memoria visual retiene hasta 24 horas de últimas observaciones, con lado y antigüedad. Al reiniciar se restaura como **pasado**, nunca como visibilidad actual.
- Los cambios se confirman durante al menos un segundo y tres detecciones de fotogramas distintos. La comparación describe cambios de clases y zonas de la imagen durante el último minuto.
- Cámara obsoleta, desconexión, cambio de cámara o recogida del teléfono reinician la comparación; no se interpretan automáticamente como objetos desaparecidos. Si el móvil se mueve continuamente, la comparación visual puede seguir siendo imprecisa.
- Hasta 32 encargos de aparición, desaparición o regreso. Son de una sola ejecución, se guardan en disco y pueden cancelarse. Para desaparición se exige haber visto el objeto durante la observación continua; para regreso, una ausencia confirmada de al menos tres segundos antes de reaparecer.
- Los avisos cumplidos quedan pendientes hasta reproducirse y confirmarse desde el móvil. Si el navegador no tiene audio desbloqueado, aparece **ESCUCHAR AVISO**. La detección requiere PC y cámara activos: no vigila mientras están apagados.
- En modo sociable puede saludar tras una ausencia observada de al menos 30 segundos y comentar una recogida. No más de un comentario espontáneo cada dos minutos; no interrumpe un turno de voz en curso.
- Al comenzar a hablar, la mirada se orienta a la persona visible y conserva el seguimiento visual. **No identifica personas ni localiza voces por dirección**: el micrófono mono no permite atribuir con fiabilidad quién habla en un grupo. «Cuando vuelva» significa que vuelve a aparecer una persona en el encuadre.
- La memoria y los encargos están en `data/companion.json`, excluido de Git. Se escribe mediante reemplazo atómico; la memoria se guarda aproximadamente cada diez segundos y al cerrar. Cada interacción sigue registrándose en `data/episodes/`.

Las observaciones corresponden a **clases**, no a identidades: dos tazas no se distinguen como objetos personales. Una localización anterior pertenece al encuadre de entonces; no establece dónde está ahora un objeto fuera de cámara.

## Diagnóstico y verificación

- `GET /api/health`: servicios locales.
- `GET /api/world`: memoria, frescura de cámara y cambios confirmados.
- `GET /api/voice/status`: transcripción, errores, estado de sesiones y resultado de la última consulta semántica (causa de fallo y latencia).
- `GET /api/assistant`: preferencias, encargos y avisos pendientes.
- `POST /api/assistant/preferences`: `{"quiet": true}`.
- `DELETE /api/assistant/watches/{id}`: cancelar un encargo.
- `POST /api/assistant/notifications/{id}/ack`: confirmar un aviso.

```sh
python3 -m pytest server/tests -q
node static/tests/voice-vad.test.cjs
python3 static/tests/browser_checks.py
```

La última comprobación necesita Playwright y Chromium instalados. Usa un AudioWorklet real con señal sintética y simula HTTP, WebSocket y síntesis de voz: comprueba captura, WAV, interrupción, permisos tardíos, cierre del micro, errores, accesibilidad y tamaños de pantalla. No sustituye una prueba acústica con el Redmi, especialmente para eco y ruido ambiente.

Las consultas de Gemma disponen de 20 segundos por petición y 35 segundos en total (`GEMMA_TIMEOUT_SECONDS`, `GEMMA_TOTAL_TIMEOUT_SECONDS`), para admitir el arranque de la visión. Los fallos de servicio o de espera se distinguen de una pregunta no comprendida; `/debug` muestra el detalle técnico.
