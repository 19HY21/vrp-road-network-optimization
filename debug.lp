\* test_zero_constraint *\
Minimize
OBJ: x + 4 y + 9 z
Subject To
c1: x + y <= 5
c2: x + z >= 10
c3: - y + z = 7
c4: w >= 0
_dummy: __dummy = 0
c5: __dummy <= 0
Bounds
 __dummy = 0
 x <= 4
 -1 <= y <= 1
End
