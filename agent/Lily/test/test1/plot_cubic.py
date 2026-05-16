import matplotlib.pyplot as plt
import numpy as np

# 生成 x 值
x = np.linspace(-10, 10, 500)
# y = x^3
y = x ** 3

# 创建图像
plt.figure(figsize=(8, 6))
plt.plot(x, y, label=r'$y = x^3$', color='blue', linewidth=2)

# 标注
plt.title(r'Plot of $y = x^3$', fontsize=14)
plt.xlabel('x', fontsize=12)
plt.ylabel('y', fontsize=12)
plt.axhline(0, color='black', linewidth=0.5)
plt.axvline(0, color='black', linewidth=0.5)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(fontsize=12)

# 保存图像
plt.savefig('H:\\Lily\\agent\\Lily\\test\\test1\\cubic_plot.png', dpi=150, bbox_inches='tight')
plt.close()

print("图像已保存为 cubic_plot.png")
