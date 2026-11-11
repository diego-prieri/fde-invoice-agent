# Post: mi visión de Forward Deployed Engineer

> Borrador para LinkedIn (~270 palabras).

---

Estoy migrando mi perfil hacia Forward Deployed Engineer. Esto es lo que entiendo del rol, y por qué me convenció.

Un FDE no entrega features: entrega resultados dentro de la operación de un cliente. Es ingeniería con la cabeza puesta en el problema de otra persona.

Tres cosas que creo que lo definen:

1️⃣ **Se empieza por el problema, no por la tecnología.** Antes de elegir un modelo hay que saber quién carga las facturas, cuánto tarda, qué errores comete y qué le cuesta un atraso en el cierre.

2️⃣ **Se construye donde el producto no llega.** Integraciones, datos sucios, sistemas viejos, el comprobante sacado con el celular. Gran parte del trabajo es la realidad, no el caso feliz.

3️⃣ **Se pone control alrededor del modelo.** El LLM extrae, el código valida, una persona revisa lo dudoso y todo queda auditado. Y se mide con evals, no con intuición.

Para practicarlo armé un proyecto: un agente que lee facturas (PDF, escaneos, fotos), extrae los datos, valida CUIT, IVA y duplicados, y carga lo seguro en un ERP. Lo dudoso va a una cola de revisión con una UI.

Un aviso honesto: usa datos sintéticos y un ERP simulado, y todavía me falta medirlo con un modelo real. Prefiero decirlo así antes que mostrar un número que no puedo sostener.

Código y estado del proyecto: https://github.com/diego-prieri/fde-invoice-agent

Si trabajás como FDE: ¿qué le dirías a alguien que viene de desarrollo de producto?

#ForwardDeployedEngineer #IA #Ingeniería #LLM
