FROM ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlex/paddlex:paddlex3.0.1-paddlepaddle3.0.0-gpu-cuda11.8-cudnn8.9-trt8.6

WORKDIR /root/PaddleX/paddlex

# Install the hpi-cpu runtime required by PaddleX.
RUN paddlex --install hpi-cpu
RUN paddlex --install serving

COPY docker/PP-StructureV3.yaml /root/PaddleX/paddlex/PP-StructureV3.yaml

# Expose the PaddleX service port.
EXPOSE 8080

# Run the PaddleX PP-StructureV3 pipeline service.
CMD ["paddlex", "--serve", "--pipeline", "PP-StructureV3.yaml", "--host", "0.0.0.0", "--port", "8080"]
