# projeto-robotica-eng4061

Projeto de Robótica - ENG4061

O projeto consiste em elaborar um protótipo de empilhadeira.
Para a parte mecânica, nós usamos uma roldana associada a uma corda que em conjunto com um motor de passo foi projetada para realizar o movimento vertical do garfo da empilhadeira.  

Para a parte de comunicação, foi desenvolvido um servidor em Flask com as ações possíveis para a empilhadeira (movimento para frente, trás, lateral e rotação) onde elas podem ser controladas via uma interface interativa com botões. Para comunicar com o microcontrolador escolhido foi usado a tecnologia de websockets, onde tanto o microcontolador quanto o servidor estavam hospedados na mesma rede. Por fim, o microcontrolador também retornava uma transmissão de vídeo em UDP que era exibida na interface.  

Para a parte eletrônica, foi usado o microcontrolador Raspberry Pi Zero como único controlador. Atrelado a ele foram implementados motores DC para movimento da empilahdeira e também um motor de passo para movimento do garfo. Para alimentação, foram utilizadas 2 packs de bateria 18650 com 3 unidades em série em cada. Os packs foram associdos em paralelo para fornecer mais carga e corrente.  

Para a parte de controle, optamos por não utilizar os encoders nas rodas e nem implementar controle PID. Para contornar essa escolha, cada comando enviado pela interface não era composto por uma medida quantitativa, assim cada comando correspondia a pequenos passos/movimentos de cada um dos motores.   

Quanto a montagem geral, concluímos que a versão final mostrou-se pouco organizada quanto ao manejo de fios e estruturação correta da alimentação. Para passos futuros, julgamos mais urgente uma melhor organização eletrônica bem como mais testes mecâncios para certificação de ações mais limpas e diretas do robô.
