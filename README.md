after many failed attempts installing the latest Plaits firmware I decided to convert the audio file to a .hex file.
I'm building Plaits clones and this step was always frustrating. The problem is that firmware 1.2 is only available as a .wav file, and the audio transfer method is unreliable — sometimes it works, sometimes it doesn't, with no clear reason why.
So I wrote a Python script that decodes the WAV directly to a .hex file ready to load with ST-Link and STM32CubeProgrammer. No more audio cables, no more failed transfers.
Should work for any module using the same bootloader (Rings, Marbles, Clouds, Braids). Let me know if you test it on others.

Plaits 1.2 for  STM32CubeProgrammer
