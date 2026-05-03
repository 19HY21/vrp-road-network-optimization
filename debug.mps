*SENSE:Minimize
NAME          test_zero_constraint
ROWS
 N  OBJ
 L  c1
 G  c2
 E  c3
 G  c4
 L  c5
COLUMNS
    __dummy   c5         1.000000000000e+00
    w         c4         1.000000000000e+00
    x         c1         1.000000000000e+00
    x         c2         1.000000000000e+00
    x         OBJ        1.000000000000e+00
    y         c1         1.000000000000e+00
    y         c3        -1.000000000000e+00
    y         OBJ        4.000000000000e+00
    z         c2         1.000000000000e+00
    z         c3         1.000000000000e+00
    z         OBJ        9.000000000000e+00
RHS
    RHS       c1         5.000000000000e+00
    RHS       c2         1.000000000000e+01
    RHS       c3         7.000000000000e+00
    RHS       c4         0.000000000000e+00
    RHS       c5         0.000000000000e+00
BOUNDS
 FX BND       __dummy    0.000000000000e+00
 UP BND       x          4.000000000000e+00
 LO BND       y         -1.000000000000e+00
 UP BND       y          1.000000000000e+00
ENDATA
