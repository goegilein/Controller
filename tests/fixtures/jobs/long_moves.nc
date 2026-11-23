; hand-written: long moves are split into <= 1 s segments by NCCodeInterpreter
G90
M4 P0 ; variable mode
G0 X0 Y0 Z0 F6000
G1 X30 Y0 P20 S51 F600 ; 3 s -> 3 segments
G1 X30 Y12.5 F600 ; 1.25 s -> 2 segments
G0 X0 Y0 F6000
G1 Z2 F60 ; Z only, 2 s
G4 P100
M5
